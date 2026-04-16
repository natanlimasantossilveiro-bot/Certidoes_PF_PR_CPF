import os
import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from twocaptcha import TwoCaptcha
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================
# Configuração
# =========================

load_dotenv()

API_KEY = os.getenv("TWOCAPTCHA_API_KEY")
if not API_KEY:
    raise RuntimeError("Defina TWOCAPTCHA_API_KEY no arquivo .env")

solver = TwoCaptcha(API_KEY)

URL_CONSULTA = (
    "https://servicos.receita.fazenda.gov.br/servicos/cpf/"
    "consultasituacao/consultapublica.asp"
)

# =========================
# Utilitários
# =========================

def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def normalizar_data(data: str) -> str:
    digitos = somente_digitos(data)
    if len(digitos) != 8:
        raise ValueError("A data deve estar no formato DD/MM/AAAA.")
    return f"{digitos[:2]}/{digitos[2:4]}/{digitos[4:]}"


def localizar_primeiro(page, seletores: list[str], descricao: str):
    for seletor in seletores:
        campo = page.locator(seletor).first
        try:
            campo.wait_for(state="visible", timeout=2000)
            return campo
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError(f"Não encontrei: {descricao}")


# =========================
# CAPTCHA AUTOMÁTICO
# =========================

def resolver_captcha_automatico(page):
    sitekey = page.locator("[data-sitekey]").first.get_attribute("data-sitekey")

    if not sitekey:
        raise RuntimeError("Sitekey do CAPTCHA não encontrada.")

    resultado = solver.recaptcha(
        sitekey=sitekey,
        url=URL_CONSULTA
    )

    token = resultado["code"]

    page.evaluate(
        """
        () => {
            let el = document.getElementById("g-recaptcha-response");
            if (!el) {
                el = document.createElement("textarea");
                el.id = "g-recaptcha-response";
                el.name = "g-recaptcha-response";
                el.style.display = "none";
                document.body.appendChild(el);
            }
            return el;
        }
        """
    )

    page.evaluate(
        "document.getElementById('g-recaptcha-response').value = arguments[0];",
        token
    )


# =========================
# Automação
# =========================

class ConsultaCpfAutomacao:
    def __init__(self, pasta_saida: Path, headless: bool = True) -> None:
        self.pasta_saida = pasta_saida
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cpf: Optional[str] = None

    def iniciar(self, cpf: str, nascimento: str) -> None:
        self.fechar()

        cpf_limpo = somente_digitos(cpf)
        if len(cpf_limpo) != 11:
            raise ValueError("CPF inválido.")

        nascimento_formatado = normalizar_data(nascimento)

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            channel="chrome",
            headless=self.headless,
        )

        self.context = self.browser.new_context(
            viewport={"width": 1366, "height": 768}
        )

        self.page = self.context.new_page()
        self.page.goto(URL_CONSULTA, timeout=60000)

        campo_cpf = localizar_primeiro(
            self.page,
            ['#txtCPF', 'input[name="txtCPF"]'],
            "CPF",
        )
        campo_cpf.fill(cpf_limpo)

        campo_nasc = localizar_primeiro(
            self.page,
            ['#txtDataNascimento', 'input[name="txtDataNascimento"]'],
            "Data de nascimento",
        )
        campo_nasc.fill(nascimento_formatado)

        resolver_captcha_automatico(self.page)

        self.page.evaluate("document.getElementById('theForm').submit()")
        self.page.wait_for_load_state("networkidle", timeout=60000)

        self.cpf = cpf_limpo

    def salvar_pdf(self) -> Path:
        texto = self.page.locator("body").inner_text(timeout=10000).lower()
        if "situação cadastral" not in texto and "situacao cadastral" not in texto:
            raise RuntimeError("Página de resultado inválida.")

        self.pasta_saida.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo = self.pasta_saida / f"certidao_cpf_{self.cpf}_{timestamp}.pdf"

        self.page.pdf(
            path=str(arquivo),
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
        )

        self.fechar()
        return arquivo

    def urls_abertas(self) -> list[str]:
        if not self.context:
            return []
        return [p.url for p in self.context.pages]

    def fechar(self) -> None:
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cpf = None


# =========================
# Execução direta (CLI)
# =========================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpf", required=True)
    parser.add_argument("--nascimento", required=True)
    parser.add_argument("--saida", default="certidoes")
    args = parser.parse_args()

    automacao = ConsultaCpfAutomacao(
        pasta_saida=Path(args.saida),
        headless=True,
    )

    try:
        automacao.iniciar(args.cpf, args.nascimento)
        arquivo = automacao.salvar_pdf()
        print(f"PDF salvo em: {arquivo}")
    except Exception as e:
        automacao.fechar()
        raise e


if __name__ == "__main__":
    main()
