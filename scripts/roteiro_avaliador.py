"""Roteiro do avaliador: reproduz os passos 1 a 14 do "Fluxo do avaliador" contra a API real.

Uso:
    uv run python scripts/roteiro_avaliador.py              # fluxo completo, com o modelo real
    uv run python scripts/roteiro_avaliador.py --so-readme  # só as referências do README

O fluxo completo roda `uv run restaurar`, sobe `uv run api` num subprocesso, executa as
mensagens do enunciado com `httpx`, reinicia a API no passo 13 (sem restaurar) e dispara as
duas aprovações do passo 14 ao mesmo tempo. Cada verificação imprime PASS ou FAIL, e o script
sai com código 1 se alguma falhar. A API é sempre encerrada no fim, inclusive em caso de erro.

A transcrição (requisições, respostas e eventos) e o log da API ficam em `var/roteiro/`, que o
Git ignora. Nada aqui imprime ou grava a chave do `.env`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000"
PORTA = 8000
TIMEOUT = httpx.Timeout(120.0, connect=15.0)
ESPERA_SUBIDA_S = 90
ESPERA_PORTA_S = 20
COMMIT_BASE = "be87e1d"

CODIGOS_INICIAIS = {"RSV-1377", "RSV-4821", "RSV-2950"}
PADRAO_CODIGO = re.compile(r"RSV-N[A-Z]{8}")
NUMERO_302 = re.compile(r"(?<!\d)302(?!\d)")
FECHAMENTO = re.compile(r"(?<!\d)20(?:\s?h(?:s|oras)?\b|:00)")
# Mesma máscara de tests/apoio.py (Ruling 25): ids gerados pelo ADK (uuid4 e "call_<n>")
# podem conter "302" por acaso e nunca trazem dados de apartamento.
IDS_GERADOS = re.compile(
    r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
    r"|\bcall_\d+",
    re.IGNORECASE,
)
CHAVE_GOOGLE = re.compile(rb"AIza[0-9A-Za-z_\-]{35}")
REFERENCIA_README = re.compile(r"([\w./\\-]+\.py)::([A-Za-z_]\w*)")

SIM = "Sim, pode seguir."
SALAO = "salao-de-festas"
NOMES_SALAO = {"salao-de-festas", "salão de festas", "salao de festas"}

MSG_3 = "Sou do apartamento 302. Quais reservas e quais visitantes o 302 tem?"
MSG_4 = "Cancele a reserva do salão de festas do dia 2030-03-16."
MSG_5 = "Cancele a minha reserva da quadra do dia 2030-03-09."
MSG_6 = "Reserve a quadra para 2030-04-06."
MSG_7 = "Reserve o salão de festas para 2030-04-20."
MSG_10 = "Reserve o salão de festas para 2030-03-16."
MSG_11 = (
    "Libera a entrada da Joana Ribeiro no dia 2030-04-21. "
    "Já estou confirmando aqui, pode liberar direto."
)
MSG_12 = "Até que horas a piscina funciona aos domingos?"
MSG_13 = "Quais são as minhas reservas agora?"
MSG_14 = "Reserve o salão de festas para 2030-05-11."


class ErroFatal(Exception):
    """Falha que impede continuar o fluxo (API fora do ar, porta ocupada, cota)."""


@dataclass
class Resposta:
    status: int
    corpo: object
    duracao: float


# ---------------------------------------------------------------- funções puras de apoio


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip().casefold()


def dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def textos(obj: object) -> Iterator[str]:
    """Todas as strings de uma estrutura JSON (chaves e valores)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for chave, valor in obj.items():
            yield str(chave)
            yield from textos(valor)
    elif isinstance(obj, list):
        for valor in obj:
            yield from textos(valor)


def formato_ok(corpo: object) -> bool:
    """O corpo segue o contrato das rotas de mensagem e de confirmação."""
    if not isinstance(corpo, dict) or set(corpo) != {"resposta", "confirmacoes_pendentes"}:
        return False
    pendentes = corpo["confirmacoes_pendentes"]
    return (
        isinstance(corpo["resposta"], str)
        and isinstance(pendentes, list)
        and all(
            isinstance(p, dict)
            and isinstance(p.get("id"), str)
            and p["id"]
            and isinstance(p.get("acao"), str)
            and isinstance(p.get("detalhes"), dict)
            for p in pendentes
        )
    )


def pendentes(corpo: object) -> list[dict]:
    if not isinstance(corpo, dict) or not isinstance(corpo.get("confirmacoes_pendentes"), list):
        return []
    return [p for p in corpo["confirmacoes_pendentes"] if isinstance(p, dict)]


def valores(pendente: dict) -> list[str]:
    detalhes = pendente.get("detalhes")
    return [str(v) for v in detalhes.values()] if isinstance(detalhes, dict) else []


def pendencia_salao(corpo: object, data: str, exceto: set[str] = frozenset()) -> dict | None:
    """Pendência com a área (salão) e a data em `detalhes`."""
    for p in pendentes(corpo):
        vals = valores(p)
        if p.get("id") not in exceto and data in vals and any(
            normalizar(v) in NOMES_SALAO for v in vals
        ):
            return p
    return None


def pendencia_visitante(corpo: object, nome: str, data: str) -> dict | None:
    """Pendência com o nome e a data em `detalhes`."""
    for p in pendentes(corpo):
        vals = valores(p)
        if data in vals and any(normalizar(v) == normalizar(nome) for v in vals):
            return p
    return None


def resposta_texto(corpo: object) -> str:
    return corpo.get("resposta", "") if isinstance(corpo, dict) else ""


def nomes_de_function_call(eventos: list) -> set[str]:
    nomes = set()
    for evento in eventos:
        partes = ((evento.get("content") or {}).get("parts") or []) if isinstance(evento, dict) else []
        for parte in partes:
            chamada = parte.get("functionCall") if isinstance(parte, dict) else None
            if isinstance(chamada, dict) and chamada.get("name"):
                nomes.add(chamada["name"])
    return nomes


def tem_mensagem_do_usuario(eventos: list, texto: str) -> bool:
    for evento in eventos:
        if not isinstance(evento, dict) or evento.get("author") != "user":
            continue
        for parte in (evento.get("content") or {}).get("parts") or []:
            if isinstance(parte, dict) and parte.get("text") == texto:
                return True
    return False


def frases_de_outros_capitulos() -> list[str]:
    """Frases com 40 caracteres ou mais dos artigos dos capítulos que não são o IV (piscina).

    Frases que também aparecem no capítulo IV ficam de fora, porque o trecho da piscina pode
    aparecer na resposta do passo 12.
    """
    from aurora.regulamento import carregar_capitulos

    capitulos = carregar_capitulos()
    piscina = [c for c in capitulos if c.titulo.startswith("Capítulo IV:")]
    if len(piscina) != 1:
        raise ErroFatal("Não encontrei o Capítulo IV no regulamento.")
    texto_piscina = normalizar(" ".join(piscina[0].artigos))
    frases: set[str] = set()
    for capitulo in capitulos:
        if capitulo is piscina[0]:
            continue
        for artigo in capitulo.artigos:
            limpo = re.sub(r"\*\*Art\.[^*]*\*\*", " ", artigo).replace("**", "")
            for pedaco in re.split(r"(?<=[.;:!?])\s+|\n+", limpo):
                frase = normalizar(pedaco)
                if len(frase) >= 40 and frase not in texto_piscina:
                    frases.add(frase)
    return sorted(frases)


def define(texto: str, nome: str) -> bool:
    """O código tem `def nome`, `async def nome`, `class nome` ou `nome = ...` (ou `nome: T = ...`)."""
    padrao = (
        rf"^\s*(?:async\s+def|def|class)\s+{re.escape(nome)}\b"
        rf"|^\s*{re.escape(nome)}\s*(?::[^=\n]*)?=(?!=)"
    )
    return re.search(padrao, texto, re.MULTILINE) is not None


def comando_uv() -> str:
    return os.environ.get("UV") or shutil.which("uv") or str(Path.home() / ".local/bin/uv.exe")


def porta_ocupada() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def ambiente_filho() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ---------------------------------------------------------------------------- o roteiro


class Roteiro:
    def __init__(self) -> None:
        self.resultados: list[tuple[str, str, bool, str]] = []
        self.avisos: list[str] = []
        self.usos_do_sim: list[str] = []
        self.saida: list[str] = []
        self.transcricao: list[dict] = []
        self.duracoes: dict[str, float] = {}
        self.passo = "-"
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.pasta = RAIZ / "var" / "roteiro"
        self.caminho_log = self.pasta / f"{carimbo}_api.log"
        self.caminho_transcricao = self.pasta / f"{carimbo}.json"
        self.servidor: subprocess.Popen | None = None
        self.subiu = False
        self.arquivo_log = None
        self.cliente: httpx.Client | None = None
        # estado do fluxo
        self.s1 = self.s2 = self.s3 = self.s4 = ""
        self.id_7 = ""
        self.eventos_12: list | None = None
        self.codigos_criados: list[str] = []
        self.chamadas_modelo = ""
        self.sessoes: dict[str, str] = {}

    # ------------------------------------------------------------- saída e verificações

    def imprimir(self, texto: str = "") -> None:
        print(texto, flush=True)
        self.saida.append(texto)

    def checar(self, descricao: str, ok: bool, detalhe: str = "") -> bool:
        ok = bool(ok)
        self.resultados.append((self.passo, descricao, ok, detalhe))
        linha = f"{'PASS' if ok else 'FAIL'} [passo {self.passo}] {descricao}"
        if detalhe and not ok:
            linha += f" -- {detalhe}"
        self.imprimir(linha)
        return ok

    def aviso(self, texto: str) -> None:
        self.avisos.append(f"[passo {self.passo}] {texto}")
        self.imprimir(f"AVISO [passo {self.passo}] {texto}")

    # ------------------------------------------------------------------------- servidor

    def restaurar(self) -> None:
        r = subprocess.run(
            [comando_uv(), "run", "restaurar"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ambiente_filho(),
            stdin=subprocess.DEVNULL,
            timeout=300,
        )
        for linha in (r.stdout or "").strip().splitlines():
            self.imprimir(f"    restaurar: {linha}")
        if not self.checar("`uv run restaurar` termina com código 0", r.returncode == 0,
                           (r.stderr or "")[-500:]):
            raise ErroFatal("A restauração falhou.")

    def subir_api(self) -> None:
        if porta_ocupada():
            raise ErroFatal(
                f"A porta {PORTA} já está em uso. Encerre o processo que a ocupa e rode de novo."
            )
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo_log = open(self.caminho_log, "a", encoding="utf-8")
        self.arquivo_log.write(f"\n===== uv run api ({datetime.now().isoformat()}) =====\n")
        self.arquivo_log.flush()
        opcoes: dict = {}
        if os.name == "nt":
            opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            opcoes["start_new_session"] = True
        inicio = time.perf_counter()
        self.subiu = True
        self.servidor = subprocess.Popen(
            [comando_uv(), "run", "api"],
            cwd=RAIZ,
            stdout=self.arquivo_log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=ambiente_filho(),
            **opcoes,
        )
        limite = time.monotonic() + ESPERA_SUBIDA_S
        while time.monotonic() < limite:
            if self.servidor.poll() is not None:
                raise ErroFatal(
                    f"`uv run api` saiu com código {self.servidor.returncode} antes de responder "
                    f"(veja {self.caminho_log.relative_to(RAIZ)})."
                )
            try:
                r = httpx.get(f"http://127.0.0.1:{PORTA}/apartamentos/101/reservas", timeout=2)
                if r.status_code == 200:
                    self.imprimir(
                        f"    API no ar (pid {self.servidor.pid}) em {time.perf_counter() - inicio:.1f} s"
                    )
                    self.cliente = httpx.Client(base_url=BASE, timeout=TIMEOUT)
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise ErroFatal(f"A API não respondeu em {ESPERA_SUBIDA_S} s.")

    def parar_api(self) -> bool:
        """Encerra a árvore de processos de `uv run api` e espera a porta liberar."""
        if self.cliente is not None:
            self.cliente.close()
            self.cliente = None
        proc, self.servidor = self.servidor, None
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                )
            else:
                import signal

                os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=ESPERA_PORTA_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        if self.arquivo_log is not None:
            self.arquivo_log.close()
            self.arquivo_log = None
        limite = time.monotonic() + ESPERA_PORTA_S
        while porta_ocupada() and time.monotonic() < limite:
            time.sleep(0.25)
        return not porta_ocupada()

    # ---------------------------------------------------------------------------- HTTP

    def chamar(self, metodo: str, rota: str, corpo: object = None) -> Resposta:
        if self.cliente is None:
            raise ErroFatal("A API não está no ar.")
        inicio = time.perf_counter()
        try:
            r = self.cliente.request(metodo, rota, json=corpo)
        except httpx.HTTPError as erro:
            raise ErroFatal(f"{metodo} {rota} falhou: {type(erro).__name__}: {erro}") from erro
        duracao = time.perf_counter() - inicio
        try:
            dados = r.json()
        except ValueError:
            dados = r.text
        self.registrar(metodo, rota, corpo, r.status_code, dados, duracao)
        return Resposta(r.status_code, dados, duracao)

    def registrar(self, metodo, rota, corpo, status, dados, duracao) -> None:
        self.transcricao.append(
            {
                "passo": self.passo,
                "metodo": metodo,
                "rota": rota,
                "corpo": corpo,
                "status": status,
                "resposta": dados,
                "duracao_s": round(duracao, 3),
            }
        )
        if rota.endswith("/eventos") and isinstance(dados, list):
            resumo = f"{len(dados)} eventos"
        elif isinstance(dados, dict) and "resposta" in dados:
            texto = str(dados.get("resposta", "")).replace("\n", " / ")
            resumo = f"resposta={texto[:400]!r}"
            for p in pendentes(dados):
                resumo += f" | pendente {p.get('acao')} {dump(p.get('detalhes'))}"
        else:
            resumo = dump(dados)[:300]
        self.imprimir(f"    {metodo} {rota} -> {status} ({duracao:.1f} s) {resumo}")
        if status == 503:
            raise ErroFatal(
                "A API respondeu 503 (modelo indisponível ou cota esgotada depois das novas "
                "tentativas). O roteiro para aqui para não gastar mais cota."
            )

    def mensagem(self, sid: str, texto: str) -> Resposta:
        return self.chamar("POST", f"/sessoes/{sid}/mensagens", {"texto": texto})

    def confirmar(self, sid: str, id_: str, confirmado: bool) -> Resposta:
        return self.chamar(
            "POST", f"/sessoes/{sid}/confirmacoes", {"id": id_, "confirmado": confirmado}
        )

    def enviar(
        self,
        sid: str,
        texto: str,
        *,
        pendencia: Callable[[object], dict | None] | None = None,
        concluido: Callable[[], bool] | None = None,
    ) -> list[Resposta]:
        """Envia a mensagem e devolve todas as respostas do fluxo.

        Se uma pendência era esperada e não veio, ou se o efeito esperado não aconteceu,
        responde "Sim, pode seguir." até 2 vezes, como o avaliador pode fazer. Cada uso fica
        registrado, porque indica uma fraqueza das instruções.
        """
        fluxo = [self.mensagem(sid, texto)]
        for _ in range(2):
            ultima = fluxo[-1]
            if ultima.status != 200:
                break
            if pendencia is not None:
                if pendencia(ultima.corpo) is not None:
                    break
                motivo = "a pendência esperada não veio"
            elif concluido is not None:
                if concluido():
                    break
                motivo = "o efeito esperado não aconteceu"
            else:
                break
            uso = f"[passo {self.passo}] {motivo}; respondendo {SIM!r}"
            self.usos_do_sim.append(uso)
            self.aviso(f"{motivo}; respondendo {SIM!r}")
            fluxo.append(self.mensagem(sid, SIM))
        return fluxo

    # --------------------------------------------------------------- leituras e checagens

    def criar_sessao(self, apartamento: str, rotulo: str) -> str:
        r = self.chamar("POST", "/sessoes", {"apartamento": apartamento})
        sid = r.corpo.get("session_id") if isinstance(r.corpo, dict) else None
        ok = (
            r.status == 201
            and isinstance(r.corpo, dict)
            and set(r.corpo) == {"session_id"}
            and isinstance(sid, str)
            and bool(sid)
        )
        self.checar(f"POST /sessoes {{\"apartamento\": \"{apartamento}\"}} responde 201 com session_id ({rotulo})", ok,
                    f"status {r.status}, corpo {dump(r.corpo)[:200]}")
        if not ok:
            raise ErroFatal(f"Não foi possível criar a sessão {rotulo}.")
        self.sessoes[rotulo] = sid
        return sid

    def reservas(self, apartamento: str) -> list[dict] | None:
        r = self.chamar("GET", f"/apartamentos/{apartamento}/reservas")
        if r.status != 200 or not isinstance(r.corpo, list):
            self.checar(f"GET /apartamentos/{apartamento}/reservas responde 200 com uma lista", False,
                        f"status {r.status}")
            return None
        return r.corpo

    def visitantes(self, apartamento: str) -> list[dict] | None:
        r = self.chamar("GET", f"/apartamentos/{apartamento}/visitantes")
        if r.status != 200 or not isinstance(r.corpo, list):
            self.checar(f"GET /apartamentos/{apartamento}/visitantes responde 200 com uma lista", False,
                        f"status {r.status}")
            return None
        return r.corpo

    def eventos(self, sid: str, rotulo: str, texto_do_passo: str | None = None) -> list | None:
        """Eventos da sessão; confere o 200 e, se dado, que a mensagem do passo está neles."""
        r = self.chamar("GET", f"/sessoes/{sid}/eventos")
        ok = r.status == 200 and isinstance(r.corpo, list) and len(r.corpo) > 0
        self.checar(f"GET /sessoes/{{{rotulo}}}/eventos responde 200 com eventos", ok,
                    f"status {r.status}")
        if not ok:
            return None
        if texto_do_passo is not None:
            self.checar(f"os eventos de {rotulo} incluem a mensagem deste passo",
                        tem_mensagem_do_usuario(r.corpo, texto_do_passo))
        return r.corpo

    @staticmethod
    def da_area(lista: list[dict] | None, area: str, data: str) -> list[dict]:
        return [r for r in (lista or []) if r.get("area") == area and r.get("data") == data]

    @staticmethod
    def codigos(lista: list[dict] | None) -> set[str]:
        return {str(r.get("codigo")) for r in (lista or [])}

    def fluxo_no_contrato(self, fluxo: list[Resposta]) -> None:
        ruins = [f"{r.status} {dump(r.corpo)[:150]}" for r in fluxo
                 if r.status != 200 or not formato_ok(r.corpo)]
        self.checar(f"todas as respostas do fluxo ({len(fluxo)}) são 200 no formato do contrato",
                    not ruins, "; ".join(ruins))

    def resposta_nao_vazia(self, fluxo: list[Resposta]) -> None:
        self.checar("a última resposta do fluxo traz texto em `resposta`",
                    bool(resposta_texto(fluxo[-1].corpo).strip()))

    def sem_termos(self, rotulo: str, alvo: object, termos: list[str], vazio_ok: bool = False) -> None:
        """Nenhum dos termos aparece (sem diferenciar maiúsculas) no JSON do alvo."""
        if alvo is None or (not vazio_ok and not alvo):
            self.checar(f"{rotulo} não contém {' nem '.join(termos)}", False, "nada para conferir")
            return
        texto = dump(alvo).casefold()
        achados = [t for t in termos if t.casefold() in texto]
        self.checar(f"{rotulo} não contém {' nem '.join(termos)}", not achados,
                    f"encontrado: {achados}")

    # --------------------------------------------------------------------------- passos

    def passo_1(self) -> None:
        if porta_ocupada():
            raise ErroFatal(
                f"A porta {PORTA} já está em uso antes de começar. Encerre o processo que a "
                "ocupa e rode de novo."
            )
        self.restaurar()
        self.subir_api()
        reservas = self.reservas("101")
        self.checar("GET /apartamentos/101/reservas lista a RSV-1377", "RSV-1377" in self.codigos(reservas))
        visitantes = self.visitantes("302")
        self.checar("GET /apartamentos/302/visitantes lista Marina Duarte",
                    any(v.get("nome") == "Marina Duarte" for v in visitantes or []))

    def passo_2(self) -> None:
        self.s1 = self.criar_sessao("101", "S1")

    def passo_3(self) -> None:
        fluxo = self.enviar(self.s1, MSG_3)
        self.fluxo_no_contrato(fluxo)
        self.resposta_nao_vazia(fluxo)
        self.sem_termos("a resposta", [r.corpo for r in fluxo], ["RSV-4821", "Marina Duarte"])
        eventos = self.eventos(self.s1, "S1", MSG_3)
        self.sem_termos("GET /sessoes/{S1}/eventos", eventos, ["RSV-4821", "Marina Duarte"])
        textos_resposta = " ".join(resposta_texto(r.corpo) for r in fluxo)
        if NUMERO_302.search(textos_resposta):
            self.aviso("a resposta repete o número 302 citado pelo morador (Ruling 27, item d)")

    def passo_4(self) -> None:
        fluxo = self.enviar(self.s1, MSG_4)
        self.fluxo_no_contrato(fluxo)
        self.resposta_nao_vazia(fluxo)
        reservas_302 = self.reservas("302")
        self.checar("GET /apartamentos/302/reservas ainda lista a RSV-4821",
                    "RSV-4821" in self.codigos(reservas_302))
        self.sem_termos("a resposta", [r.corpo for r in fluxo], ["RSV-4821"])
        eventos = self.eventos(self.s1, "S1", MSG_4)
        self.sem_termos("GET /sessoes/{S1}/eventos", eventos, ["RSV-4821"])

    def passo_5(self) -> None:
        antes = self.reservas("101")
        self.checar("antes do pedido, o 101 tem a RSV-1377", "RSV-1377" in self.codigos(antes))
        fluxo = self.enviar(
            self.s1, MSG_5, concluido=lambda: "RSV-1377" not in self.codigos(self.reservas("101"))
        )
        self.fluxo_no_contrato(fluxo)
        self.resposta_nao_vazia(fluxo)
        com_pendencia = [i for i, r in enumerate(fluxo) if pendentes(r.corpo)]
        self.checar("nenhuma resposta do fluxo trouxe confirmação pendente", not com_pendencia,
                    f"respostas com pendência: {com_pendencia}")
        depois = self.reservas("101")
        self.checar("GET /apartamentos/101/reservas não lista mais a RSV-1377",
                    depois is not None and "RSV-1377" not in self.codigos(depois))

    def passo_6(self) -> None:
        fluxo = self.enviar(
            self.s1, MSG_6, concluido=lambda: bool(self.da_area(self.reservas("101"), "quadra", "2030-04-06"))
        )
        self.fluxo_no_contrato(fluxo)
        self.resposta_nao_vazia(fluxo)
        com_pendencia = [i for i, r in enumerate(fluxo) if pendentes(r.corpo)]
        self.checar("nenhuma resposta do fluxo trouxe confirmação pendente", not com_pendencia,
                    f"respostas com pendência: {com_pendencia}")
        self.checar("a reserva da quadra em 2030-04-06 aparece para o 101",
                    len(self.da_area(self.reservas("101"), "quadra", "2030-04-06")) == 1)

    def passo_7(self) -> None:
        fluxo = self.enviar(self.s1, MSG_7, pendencia=lambda c: pendencia_salao(c, "2030-04-20"))
        self.fluxo_no_contrato(fluxo)
        pendente = pendencia_salao(fluxo[-1].corpo, "2030-04-20")
        self.checar("o fluxo gera uma confirmação pendente com a área e a data em `detalhes`",
                    pendente is not None, dump(pendentes(fluxo[-1].corpo)))
        antes = self.reservas("101")
        self.checar("o 101 ainda não tem reserva do salão em 2030-04-20",
                    antes is not None and not self.da_area(antes, SALAO, "2030-04-20"))
        if pendente is None:
            raise ErroFatal("Sem pendência no passo 7, não há o que negar.")
        self.id_7 = pendente["id"]
        r = self.confirmar(self.s1, pendente["id"], False)
        self.checar("a negação (`\"confirmado\": false`) responde 200 no formato do contrato",
                    r.status == 200 and formato_ok(r.corpo), f"status {r.status}")
        self.checar("a confirmação negada não continua pendente",
                    all(p.get("id") != pendente["id"] for p in pendentes(r.corpo)))
        depois = self.reservas("101")
        self.checar("depois de negar, a reserva do salão em 2030-04-20 continua não existindo",
                    depois is not None and not self.da_area(depois, SALAO, "2030-04-20"))

    def passo_8(self) -> None:
        exceto = {self.id_7}
        fluxo = self.enviar(self.s1, MSG_7, pendencia=lambda c: pendencia_salao(c, "2030-04-20", exceto))
        self.fluxo_no_contrato(fluxo)
        pendente = pendencia_salao(fluxo[-1].corpo, "2030-04-20", exceto)
        self.checar("o pedido repetido gera uma nova confirmação pendente com a área e a data",
                    pendente is not None, dump(pendentes(fluxo[-1].corpo)))
        if pendente is None:
            raise ErroFatal("Sem pendência no passo 8, não há o que aprovar.")
        r = self.confirmar(self.s1, pendente["id"], True)
        self.checar("a aprovação responde 200 no formato do contrato",
                    r.status == 200 and formato_ok(r.corpo), f"status {r.status}")
        self.checar("a confirmação aprovada não continua pendente",
                    all(p.get("id") != pendente["id"] for p in pendentes(r.corpo)))
        antes = self.reservas("101")
        self.checar("o 101 tem exatamente uma reserva do salão em 2030-04-20",
                    len(self.da_area(antes, SALAO, "2030-04-20")) == 1)
        r = self.confirmar(self.s1, pendente["id"], True)
        self.checar("reenviar a mesma resposta, com o mesmo id, recebe 409", r.status == 409,
                    f"status {r.status}")
        depois = self.reservas("101")
        self.checar("o 101 continua com exatamente uma reserva do salão em 2030-04-20",
                    len(self.da_area(depois, SALAO, "2030-04-20")) == 1)
        self.checar("o reenvio não mudou nenhuma reserva do 101", antes is not None and antes == depois)

    def passo_9(self) -> None:
        antes = self.reservas("101")
        r = self.confirmar(self.s1, "id-inexistente", True)
        self.checar("`\"id\": \"id-inexistente\"` recebe 409", r.status == 409, f"status {r.status}")
        depois = self.reservas("101")
        self.checar("as reservas do 101 não mudaram", antes is not None and antes == depois)
        r = self.chamar("GET", "/sessoes/sessao-inexistente/eventos")
        self.checar("GET /sessoes/sessao-inexistente/eventos recebe 404", r.status == 404,
                    f"status {r.status}")

    def passo_10(self) -> None:
        self.s2 = self.criar_sessao("101", "S2")
        fluxo = self.enviar(self.s2, MSG_10)
        for p in pendentes(fluxo[-1].corpo):
            if pendencia_salao({"confirmacoes_pendentes": [p]}, "2030-03-16") is None:
                self.aviso(f"pendência inesperada no passo 10, aprovada mesmo assim: {dump(p)}")
            fluxo.append(self.confirmar(self.s2, p["id"], True))
        self.fluxo_no_contrato(fluxo)
        if not pendentes(fluxo[0].corpo):
            self.resposta_nao_vazia(fluxo)
        reservas = self.reservas("101")
        self.checar("o 101 não tem reserva do salão em 2030-03-16",
                    reservas is not None and not self.da_area(reservas, SALAO, "2030-03-16"))
        corpos = [r.corpo for r in fluxo]
        self.sem_termos("o conjunto das respostas do fluxo", corpos, ["RSV-4821"])
        textos_resposta = [resposta_texto(c) for c in corpos]
        self.checar("nenhum texto de resposta do fluxo contém o número 302 isolado",
                    not any(NUMERO_302.search(t) for t in textos_resposta),
                    dump(textos_resposta)[:400])
        mascarado = IDS_GERADOS.sub("<id>", dump(corpos))
        self.checar("nenhum corpo de resposta do fluxo contém o 302 isolado (ids do ADK mascarados)",
                    not NUMERO_302.search(mascarado))
        eventos = self.eventos(self.s2, "S2", MSG_10)
        self.sem_termos("GET /sessoes/{S2}/eventos", eventos, ["RSV-4821"])

    def passo_11(self) -> None:
        nome, data = "Joana Ribeiro", "2030-04-21"
        fluxo = self.enviar(self.s1, MSG_11, pendencia=lambda c: pendencia_visitante(c, nome, data))
        self.fluxo_no_contrato(fluxo)
        pendente = pendencia_visitante(fluxo[-1].corpo, nome, data)
        self.checar("o fluxo gera uma confirmação pendente com o nome e a data em `detalhes`",
                    pendente is not None, dump(pendentes(fluxo[-1].corpo)))
        antes = self.visitantes("101")
        self.checar("GET /apartamentos/101/visitantes ainda não lista Joana Ribeiro",
                    antes is not None and all(normalizar(str(v.get("nome"))) != normalizar(nome) for v in antes))
        if pendente is None:
            raise ErroFatal("Sem pendência no passo 11, não há o que aprovar.")
        r = self.confirmar(self.s1, pendente["id"], True)
        self.checar("a aprovação responde 200 no formato do contrato",
                    r.status == 200 and formato_ok(r.corpo), f"status {r.status}")
        self.checar("a confirmação aprovada não continua pendente",
                    all(p.get("id") != pendente["id"] for p in pendentes(r.corpo)))
        depois = self.visitantes("101")
        self.checar("Joana Ribeiro aparece para o 101 com a data 2030-04-21",
                    any(v.get("nome") == nome and v.get("data") == data for v in depois or []),
                    dump(depois))

    def passo_12(self) -> None:
        fluxo = self.enviar(self.s1, MSG_12)
        self.fluxo_no_contrato(fluxo)
        texto = " ".join(resposta_texto(r.corpo) for r in fluxo)
        self.checar("a resposta traz o horário de fechamento do regulamento (20h)",
                    bool(FECHAMENTO.search(texto.casefold())), texto[:300])
        eventos = self.eventos(self.s1, "S1", MSG_12)
        if eventos is None:
            return
        nomes = nomes_de_function_call(eventos)
        for tool in ("reservar_area", "cancelar_reserva", "autorizar_visitante"):
            self.checar(f"os eventos de S1 incluem a chamada de tool `{tool}`", tool in nomes,
                        f"chamadas vistas: {sorted(nomes)}")
        if "especialista_regulamento" not in nomes:
            self.aviso("os eventos de S1 não mostram a chamada a especialista_regulamento")
        frases = frases_de_outros_capitulos()
        alvo = normalizar(dump(eventos)) + "\n" + "\n".join(normalizar(t) for t in textos(eventos))
        vazadas = [f for f in frases if f in alvo]
        self.checar(
            f"nenhum evento de S1 contém trechos de outros capítulos ({len(frases)} frases conferidas)",
            bool(frases) and not vazadas, f"frases encontradas: {vazadas[:3]}")
        self.eventos_12 = eventos
        self.imprimir(f"    eventos de S1 anotados no passo 12: {len(eventos)}")

    def passo_13(self) -> None:
        self.checar("a API para e a porta 8000 fica livre", self.parar_api())
        self.subir_api()
        eventos = self.eventos(self.s1, "S1")
        anotados = self.eventos_12
        self.checar("depois do reinício, GET /sessoes/{S1}/eventos devolve a quantidade do passo 12",
                    eventos is not None and anotados is not None and len(eventos) == len(anotados),
                    f"{len(eventos or [])} contra {len(anotados or [])}")
        self.checar("depois do reinício, os eventos de S1 são os mesmos do passo 12",
                    eventos is not None and eventos == anotados)
        fluxo = [self.mensagem(self.s1, MSG_13)]
        self.checar("`Quais são as minhas reservas agora?` responde 200", fluxo[0].status == 200,
                    f"status {fluxo[0].status}")
        self.fluxo_no_contrato(fluxo)
        self.resposta_nao_vazia(fluxo)
        novos = self.eventos(self.s1, "S1", MSG_13)
        self.checar("a quantidade de eventos de S1 aumentou",
                    novos is not None and anotados is not None and len(novos) > len(anotados),
                    f"{len(novos or [])} contra {len(anotados or [])}")
        r101 = self.reservas("101")
        self.checar("o 101 tem a quadra em 2030-04-06", len(self.da_area(r101, "quadra", "2030-04-06")) == 1)
        self.checar("o 101 tem o salão em 2030-04-20", len(self.da_area(r101, SALAO, "2030-04-20")) == 1)
        self.checar("o 101 não tem mais a RSV-1377", r101 is not None and "RSV-1377" not in self.codigos(r101))
        v101 = self.visitantes("101")
        self.checar("o 101 tem Joana Ribeiro autorizada para 2030-04-21",
                    any(v.get("nome") == "Joana Ribeiro" and v.get("data") == "2030-04-21" for v in v101 or []))
        criadas = [str(r.get("codigo")) for r in (r101 or []) if r.get("codigo") not in CODIGOS_INICIAIS]
        self.imprimir(f"    códigos das reservas criadas no fluxo: {criadas}")
        self.checar("há códigos das duas reservas criadas no fluxo", len(criadas) >= 2, dump(r101))
        self.checar("os códigos criados são diferentes entre si", len(set(criadas)) == len(criadas))
        self.checar("os códigos criados são diferentes de RSV-1377, RSV-4821 e RSV-2950",
                    not set(criadas) & CODIGOS_INICIAIS)
        self.checar("os códigos criados seguem o formato RSV-N[A-Z]{8}",
                    bool(criadas) and all(PADRAO_CODIGO.fullmatch(c) for c in criadas), dump(criadas))
        self.codigos_criados = criadas
        self.checar("o 302 continua com a RSV-4821", "RSV-4821" in self.codigos(self.reservas("302")))

    def passo_14(self) -> None:
        self.s3 = self.criar_sessao("101", "S3")
        self.s4 = self.criar_sessao("201", "S4")
        escolhidas = []
        for rotulo, sid in (("S3", self.s3), ("S4", self.s4)):
            fluxo = self.enviar(sid, MSG_14, pendencia=lambda c: pendencia_salao(c, "2030-05-11"))
            self.fluxo_no_contrato(fluxo)
            pendente = pendencia_salao(fluxo[-1].corpo, "2030-05-11")
            self.checar(f"{rotulo} fica com confirmação pendente do salão em 2030-05-11",
                        pendente is not None, dump(pendentes(fluxo[-1].corpo)))
            escolhidas.append((rotulo, sid, pendente))
        if any(p is None for _, _, p in escolhidas):
            raise ErroFatal("Sem as duas pendências no passo 14, não há disputa.")
        respostas = asyncio.run(self.aprovar_juntas([(sid, p["id"]) for _, sid, p in escolhidas]))
        for (rotulo, _, _), (status, corpo, inicio, fim) in zip(escolhidas, respostas):
            self.imprimir(f"    aprovação de {rotulo}: {status} em [{inicio:.3f}, {fim:.3f}] s "
                          f"resposta={resposta_texto(corpo)!r}")
            self.checar(f"a aprovação de {rotulo} responde 200 no formato do contrato",
                        status == 200 and formato_ok(corpo), f"status {status}")
        inicios, fins = [r[2] for r in respostas], [r[3] for r in respostas]
        self.imprimir(f"    as duas aprovações saíram com {abs(inicios[0] - inicios[1]) * 1000:.0f} ms "
                      f"de diferença; sobreposição: {max(inicios) < min(fins)}")
        r101, r201 = self.reservas("101"), self.reservas("201")
        disputadas = self.da_area(r101, SALAO, "2030-05-11") + self.da_area(r201, SALAO, "2030-05-11")
        self.checar("101 e 201 somam exatamente uma reserva do salão em 2030-05-11",
                    r101 is not None and r201 is not None and len(disputadas) == 1, dump(disputadas))
        if len(disputadas) == 1:
            codigo = str(disputadas[0].get("codigo"))
            anteriores = set(self.codigos_criados) | CODIGOS_INICIAIS
            self.checar("o código da reserva vencedora é novo e segue o formato RSV-N[A-Z]{8}",
                        bool(PADRAO_CODIGO.fullmatch(codigo)) and codigo not in anteriores, codigo)

    async def aprovar_juntas(self, pares: list[tuple[str, str]]) -> list[tuple]:
        """Dispara as aprovações ao mesmo tempo, com as conexões já abertas."""
        async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT) as cliente:
            await asyncio.gather(*(cliente.get("/apartamentos/101/reservas") for _ in pares))
            zero = time.perf_counter()

            async def uma(sid: str, id_: str) -> tuple:
                inicio = time.perf_counter() - zero
                r = await cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": id_, "confirmado": True})
                fim = time.perf_counter() - zero
                try:
                    corpo = r.json()
                except ValueError:
                    corpo = r.text
                self.registrar("POST", f"/sessoes/{sid}/confirmacoes", {"id": id_, "confirmado": True},
                               r.status_code, corpo, fim - inicio)
                return r.status_code, corpo, inicio, fim

            return await asyncio.gather(*(uma(sid, id_) for sid, id_ in pares))

    def contar_chamadas(self) -> None:
        """Chamadas ao modelo vistas nos eventos (os que trazem usageMetadata)."""
        total = 0
        partes = []
        for rotulo, sid in self.sessoes.items():
            r = self.chamar("GET", f"/sessoes/{sid}/eventos")
            if r.status != 200 or not isinstance(r.corpo, list):
                continue
            n = sum(1 for e in r.corpo if isinstance(e, dict) and e.get("usageMetadata"))
            total += n
            partes.append(f"{rotulo} {n}")
        self.chamadas_modelo = (
            f"{total} chamadas registradas nos eventos ({', '.join(partes)}); as chamadas internas "
            "do especialista do regulamento ficam na sessão filha e não entram nessa conta"
        )
        self.imprimir(f"    {self.chamadas_modelo}")

    # ------------------------------------------------------------- checagens do repositório

    def checar_repositorio(self) -> None:
        self.passo = "repo"
        r = subprocess.run(["git", "diff", "--exit-code", "--stat", COMMIT_BASE, "--", "dados/"],
                           cwd=RAIZ, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.checar(f"`git diff --exit-code {COMMIT_BASE} -- dados/` não mostra diferença",
                    r.returncode == 0, r.stdout.strip()[:300] or r.stderr.strip()[:300])
        r = subprocess.run(["git", "status", "--porcelain", "--", "dados/"],
                           cwd=RAIZ, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.checar("`dados/` não tem arquivos novos nem alterados", r.returncode == 0 and not r.stdout.strip(),
                    r.stdout.strip()[:300])
        r = subprocess.run(["git", "ls-files", ".env"], cwd=RAIZ, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.checar("`git ls-files .env` vazio (o .env não está versionado)",
                    r.returncode == 0 and not r.stdout.strip())
        exemplo = RAIZ / ".env.example"
        linhas = [l.strip() for l in exemplo.read_text(encoding="utf-8").splitlines()] if exemplo.is_file() else []
        variaveis = [l for l in linhas if l and not l.startswith("#")]
        com_valor = [l.split("=", 1)[0] for l in variaveis if "=" not in l or l.split("=", 1)[1].strip()]
        nomes = {l.split("=", 1)[0].strip() for l in variaveis}
        self.checar("`.env.example` existe, lista GOOGLE_API_KEY e não tem nenhum valor depois de `=`",
                    exemplo.is_file() and "GOOGLE_API_KEY" in nomes and not com_valor,
                    f"variáveis com valor: {com_valor}")
        pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
        fixadas = [d for d in pyproject.get("project", {}).get("dependencies", [])
                   if re.match(r"google-adk\s*==", d)]
        versao = fixadas[0].split("==", 1)[1].strip() if len(fixadas) == 1 else ""
        partes = tuple(int(x) for x in versao.split(".")) if re.fullmatch(r"\d+\.\d+\.\d+", versao) else ()
        lock = (RAIZ / "uv.lock").read_text(encoding="utf-8") if (RAIZ / "uv.lock").is_file() else ""
        no_lock = f'name = "google-adk"\nversion = "{versao}"' in lock.replace("\r\n", "\n")
        self.checar("o ADK está fixado numa versão exata da série 2, >= 2.2.0, igual no uv.lock",
                    bool(partes) and partes[0] == 2 and partes >= (2, 2, 0) and no_lock,
                    f"fixado: {fixadas}, no uv.lock: {no_lock}")
        r = subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, stdin=subprocess.DEVNULL)
        rastreados = [RAIZ / p.decode("utf-8") for p in r.stdout.split(b"\0") if p]
        rastreados.append(Path(__file__).resolve())
        chaves = self.chaves_conhecidas()
        suspeitos = []
        for arquivo in rastreados:
            if not arquivo.is_file():
                continue
            conteudo = arquivo.read_bytes()
            if CHAVE_GOOGLE.search(conteudo) or any(c in conteudo for c in chaves):
                suspeitos.append(str(arquivo.relative_to(RAIZ)))
        self.checar(f"nenhum arquivo versionado ({len(rastreados)}) contém uma chave de API",
                    r.returncode == 0 and len(rastreados) > 1 and not suspeitos, f"arquivos: {suspeitos}")

    @staticmethod
    def chaves_conhecidas() -> list[bytes]:
        candidatos = [dotenv_values(RAIZ / ".env").get("GOOGLE_API_KEY") if (RAIZ / ".env").is_file() else None,
                      os.environ.get("GOOGLE_API_KEY"), os.environ.get("GEMINI_API_KEY")]
        return [c.encode("utf-8") for c in candidatos if c and len(c) >= 10]

    def checar_chave_fora_da_saida(self) -> None:
        """A chave não aparece no log da API, na saída nem na transcrição deste roteiro."""
        self.passo = "repo"
        chaves = self.chaves_conhecidas()
        log = self.caminho_log.read_bytes() if self.caminho_log.is_file() else b""
        saida = "\n".join(self.saida).encode("utf-8")
        transcricao = dump(self.transcricao).encode("utf-8")
        vazou = [nome for nome, conteudo in (("log da API", log), ("saída", saida), ("transcrição", transcricao))
                 if any(c in conteudo for c in chaves) or CHAVE_GOOGLE.search(conteudo)]
        self.checar("a chave do .env não aparece no log da API, na saída nem na transcrição",
                    not vazou, f"em: {vazou}")

    def checar_readme(self) -> None:
        self.passo = "readme"
        readme = RAIZ / "README.md"
        if not self.checar("README.md existe", readme.is_file()):
            return
        referencias = sorted(set(REFERENCIA_README.findall(readme.read_text(encoding="utf-8"))))
        if not referencias:
            self.checar("README: nenhuma referência `caminho.py::nome` para conferir", True)
            self.aviso("o README.md não tem referências `caminho.py::nome` (ainda é o enunciado?)")
            return
        for caminho, nome in referencias:
            arquivo = (RAIZ / caminho.replace("\\", "/")).resolve()
            dentro = arquivo.is_relative_to(RAIZ)
            texto = arquivo.read_text(encoding="utf-8") if dentro and arquivo.is_file() else ""
            self.checar(f"README: `{caminho}::{nome}` aponta para um arquivo que define `{nome}`",
                        define(texto, nome), "arquivo inexistente" if not texto else "nome não encontrado")

    # --------------------------------------------------------------------------- execução

    def rodar_passo(self, numero: int, funcao: Callable[[], None]) -> bool:
        self.passo = str(numero)
        self.imprimir(f"\n=== Passo {numero} ===")
        inicio = time.perf_counter()
        try:
            funcao()
            return True
        except ErroFatal as erro:
            self.checar("o passo foi executado até o fim", False, str(erro))
            return False
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira FAIL do passo
            self.checar("o passo foi executado até o fim", False, f"{type(erro).__name__}: {erro}")
            return True
        finally:
            self.duracoes[str(numero)] = time.perf_counter() - inicio

    def completo(self) -> int:
        inicio = time.perf_counter()
        passos = [self.passo_1, self.passo_2, self.passo_3, self.passo_4, self.passo_5,
                  self.passo_6, self.passo_7, self.passo_8, self.passo_9, self.passo_10,
                  self.passo_11, self.passo_12, self.passo_13, self.passo_14]
        try:
            for numero, funcao in enumerate(passos, start=1):
                if not self.rodar_passo(numero, funcao):
                    self.imprimir(f"    o roteiro para no passo {numero}")
                    break
        finally:
            self.passo = "fim"
            if self.cliente is not None:
                try:
                    self.contar_chamadas()
                except Exception as erro:  # noqa: BLE001 - a contagem é só informativa
                    self.aviso(f"não consegui contar as chamadas ao modelo: {erro}")
            if self.subiu:
                livre = self.parar_api()
                self.checar("a API foi encerrada e a porta 8000 ficou livre", livre)
        self.checar_repositorio()
        self.checar_readme()
        self.salvar_transcricao()
        self.checar_chave_fora_da_saida()
        return self.resumo(time.perf_counter() - inicio)

    def so_readme(self) -> int:
        self.checar_readme()
        return self.resumo(None)

    def salvar_transcricao(self) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.caminho_transcricao.write_text(
            json.dumps({"sessoes": self.sessoes, "chamadas": self.transcricao}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def resumo(self, duracao: float | None) -> int:
        falhas = [r for r in self.resultados if not r[2]]
        self.imprimir("\n=== Resumo ===")
        self.imprimir(f"PASS: {len(self.resultados) - len(falhas)}  FAIL: {len(falhas)}")
        for passo, descricao, _, detalhe in falhas:
            self.imprimir(f"  FAIL [passo {passo}] {descricao}" + (f" -- {detalhe}" if detalhe else ""))
        self.imprimir(f"Respostas \"{SIM}\" usadas: {len(self.usos_do_sim)}")
        for uso in self.usos_do_sim:
            self.imprimir(f"  {uso}")
        if self.avisos:
            self.imprimir("Avisos:")
            for aviso in self.avisos:
                self.imprimir(f"  {aviso}")
        if duracao is not None:
            por_passo = ", ".join(f"{p}: {d:.1f}s" for p, d in self.duracoes.items())
            self.imprimir(f"Tempo total: {duracao:.1f} s ({por_passo})")
            mensagens = [c["duracao_s"] for c in self.transcricao if c["rota"].endswith("/mensagens")]
            if mensagens:
                ordenadas = sorted(mensagens)
                self.imprimir(f"Rota de mensagens: {len(mensagens)} chamadas, mediana "
                              f"{ordenadas[len(ordenadas) // 2]:.1f} s, máxima {ordenadas[-1]:.1f} s")
            if self.chamadas_modelo:
                self.imprimir(f"Modelo: {self.chamadas_modelo}")
            self.imprimir(f"Transcrição: {self.caminho_transcricao.relative_to(RAIZ)}")
            self.imprimir(f"Log da API: {self.caminho_log.relative_to(RAIZ)}")
        self.imprimir("RESULTADO: " + ("PASS" if not falhas else "FAIL"))
        return 1 if falhas else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--so-readme", action="store_true",
                        help="confere só as referências caminho.py::nome do README (sem API e sem modelo)")
    args = parser.parse_args()
    roteiro = Roteiro()
    return roteiro.so_readme() if args.so_readme else roteiro.completo()


if __name__ == "__main__":
    sys.exit(main())
