import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


URL_CONSULTA = (
    "https://servicos.receita.fazenda.gov.br/servicos/cpf/"
    "consultasituacao/consultapublica.asp"
)


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def normalizar_data(data: str) -> str:
    digitos = somente_digitos(data)
    if len(digitos) != 8:
        raise ValueError("A data de nascimento deve estar no formato DD/MM/AAAA.")
    return f"{digitos[:2]}/{digitos[2:4]}/{digitos[4:]}"


def localizar_primeiro(page, seletores: list[str], descricao: str):
    for seletor in seletores:
        campo = page.locator(seletor).first
        try:
            campo.wait_for(state="visible", timeout=2_000)
            return campo
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError(f"Nao encontrei o campo/botao: {descricao}.")


def preencher_formulario(page, cpf: str, nascimento: str) -> None:
    campo_cpf = localizar_primeiro(
        page,
        [
            'input[name="txtCPF"]',
            "#txtCPF",
            'input[id*="CPF" i]',
            'input[name*="CPF" i]',
            'input[placeholder*="CPF" i]',
        ],
        "CPF",
    )
    campo_cpf.fill(cpf)

    campo_nascimento = localizar_primeiro(
        page,
        [
            'input[name="txtDataNascimento"]',
            "#txtDataNascimento",
            'input[id*="Nascimento" i]',
            'input[name*="Nascimento" i]',
            'input[placeholder*="Nascimento" i]',
            'input[placeholder*="Data" i]',
        ],
        "Data de nascimento",
    )
    campo_nascimento.fill(nascimento)


def obter_token_captcha(page) -> str:
    seletores = [
        "#h-recaptcha-response",
        "#g-recaptcha-response",
        'textarea[name="h-captcha-response"]',
        'textarea[name="g-recaptcha-response"]',
        'input[name="h-captcha-response"]',
        'input[name="g-recaptcha-response"]',
    ]

    for seletor in seletores:
        try:
            token = page.locator(seletor).first.input_value(timeout=500)
        except PlaywrightTimeoutError:
            continue
        if token.strip():
            return token
    return ""


def esperar_captcha_validado(page) -> None:
    try:
        page.wait_for_function(
            """
            () => {
                const seletores = [
                    '#h-recaptcha-response',
                    '#g-recaptcha-response',
                    'textarea[name="h-captcha-response"]',
                    'textarea[name="g-recaptcha-response"]',
                    'input[name="h-captcha-response"]',
                    'input[name="g-recaptcha-response"]'
                ];
                return seletores.some((seletor) => {
                    const campo = document.querySelector(seletor);
                    return campo && campo.value && campo.value.trim().length > 0;
                });
            }
            """,
            timeout=20_000,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "O CAPTCHA ainda nao foi reconhecido pela pagina da Receita. "
            "Marque o CAPTCHA no Chrome, aguarde alguns segundos e clique em Salvar PDF."
        ) from exc


def clicar_consultar(page):
    esperar_captcha_validado(page)

    botao = localizar_primeiro(
        page,
        [
            "#id_submit",
            'input[name="Enviar"][value="Consultar"]',
            'form#theForm input[type="submit"]',
            'input[type="submit"]',
            'button[type="submit"]',
            'input[value*="Consultar" i]',
            'button:has-text("Consultar")',
            'input[value*="Enviar" i]',
            'button:has-text("Enviar")',
        ],
        "Consultar",
    )

    mensagens_alerta = []
    page.on("dialog", lambda dialog: mensagens_alerta.append(dialog.message) or dialog.accept())

    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
            botao.click()
    except PlaywrightTimeoutError:
        if mensagens_alerta:
            raise RuntimeError("A Receita retornou este aviso: " + mensagens_alerta[-1])

        if not pagina_eh_resultado(page) and obter_token_captcha(page):
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
                page.evaluate("document.querySelector('#theForm').submit()")

    page.wait_for_load_state("domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    return page


def pagina_eh_resultado(page) -> bool:
    url_atual = page.url.lower()
    return "consultapublicaexibir.asp" in url_atual


def localizar_pagina_resultado(context, pagina_padrao):
    paginas = list(context.pages)
    for page in reversed(paginas):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3_000)
        except PlaywrightTimeoutError:
            pass

        if pagina_eh_resultado(page):
            return page

    return pagina_padrao


def pagina_tem_formulario_inicial(page) -> bool:
    try:
        return page.locator("#theForm, #txtCPF, #txtDataNascimento").count() > 0
    except PlaywrightTimeoutError:
        return False


def validar_pagina_resultado(page) -> None:
    if not pagina_eh_resultado(page):
        raise RuntimeError(
            "A consulta nao chegou na pagina do comprovante. "
            "Verifique se o CAPTCHA foi validado antes de clicar em Salvar PDF. "
            f"Pagina atual: {page.url}"
        )


def validar_pagina_resultado_com_contexto(page, context) -> None:
    if pagina_eh_resultado(page):
        return
    
    urls = []
    for indice, aba in enumerate(context.pages, start=1):
        urls.append(f"Aba {indice}: {aba.url}")

    raise RuntimeError(
        "A consulta nao chegou na pagina do comprovante. No Chrome da Receita, "
        "valide o CAPTCHA, clique em Consultar e aguarde o comprovante aparecer "
        "antes de clicar em Salvar PDF. Paginas abertas: " + " | ".join(urls)
    )


def validar_conteudo_resultado(page) -> None:
    texto = page.locator("body").inner_text(timeout=10_000).lower()
    if pagina_tem_formulario_inicial(page) or "preencha os campos abaixo" in texto:
        raise RuntimeError(
            "A pagina atual ainda e o formulario inicial, nao o comprovante. "
            "Valide o CAPTCHA e clique em Salvar PDF novamente."
        )

    termos_resultado = [
        "nome:",
        "situa\u00e7\u00e3o cadastral:",
        "situacao cadastral:",
        "data da inscri\u00e7\u00e3o:",
        "data da inscricao:",
        "digito verificador:",
    ]
    if not any(termo in texto for termo in termos_resultado):
        raise RuntimeError(
            "A pagina carregada nao parece ser o comprovante do CPF. "
            "O PDF nao foi salvo para evitar gerar arquivo incorreto."
        )


def salvar_pdf(page, cpf: str, pasta_saida: Path) -> Path:
    validar_pagina_resultado(page)
    validar_conteudo_resultado(page)

    pasta_saida.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_pdf = pasta_saida / f"certidao_cpf_{cpf}_{timestamp}.pdf"

    page.pdf(
        path=str(arquivo_pdf),
        format="A4",
        print_background=True,
        margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
    )
    return arquivo_pdf


class ConsultaCpfAutomacao:
    def __init__(self, pasta_saida: Path, headless: bool = False) -> None:
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
            raise ValueError("O CPF deve conter 11 digitos.")

        nascimento_formatado = normalizar_data(nascimento)
        if self.headless:
            raise RuntimeError(
                "Este fluxo exige validacao manual do CAPTCHA. Execute com navegador visivel."
            )

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            channel="chrome",
            headless=self.headless,
        )
        self.context = self.browser.new_context(
            accept_downloads=True,
            viewport={"width": 1366, "height": 768},
        )
        self.page = self.context.new_page()
        self.page.goto(URL_CONSULTA, wait_until="domcontentloaded", timeout=60_000)

        preencher_formulario(self.page, cpf_limpo, nascimento_formatado)
        self.cpf = cpf_limpo

    def consultar_e_salvar(self, enviar_automaticamente: bool = False) -> Path:
        if not self.page or not self.context or not self.cpf:
            raise RuntimeError("Inicie uma consulta antes de salvar o PDF.")

        pagina_resultado = localizar_pagina_resultado(self.context, self.page)
        if enviar_automaticamente and not pagina_eh_resultado(pagina_resultado):
            pagina_resultado = clicar_consultar(self.page)
            pagina_resultado = localizar_pagina_resultado(self.context, pagina_resultado)

        validar_pagina_resultado_com_contexto(pagina_resultado, self.context)
        arquivo_pdf = salvar_pdf(pagina_resultado, self.cpf, self.pasta_saida)
        self.fechar()
        return arquivo_pdf

    def urls_abertas(self) -> list[str]:
        if not self.context:
            return []
        return [page.url for page in self.context.pages]

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


def executar(cpf: str, nascimento: str, pasta_saida: Path, headless: bool) -> Path:
    automacao = ConsultaCpfAutomacao(pasta_saida=pasta_saida, headless=headless)
    try:
        automacao.iniciar(cpf, nascimento)
        print("\nResolva o CAPTCHA manualmente na janela do Chrome.")
        input("Depois de validar o CAPTCHA e clicar em Consultar, pressione Enter aqui...")

        arquivo_pdf = automacao.consultar_e_salvar()
        print(f"PDF salvo em: {arquivo_pdf}")
        return arquivo_pdf
    except Exception:
        automacao.fechar()
        raise


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consulta situacao cadastral do CPF e salva o comprovante em PDF."
    )
    parser.add_argument("--cpf", required=True, help="CPF com ou sem pontuacao.")
    parser.add_argument(
        "--nascimento",
        required=True,
        help="Data de nascimento no formato DD/MM/AAAA.",
    )
    parser.add_argument(
        "--saida",
        default="certidoes",
        help="Pasta onde o PDF sera salvo. Padrao: certidoes",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem abrir o navegador. Nao funciona com CAPTCHA manual.",
    )
    return parser


def main() -> None:
    args = criar_parser().parse_args()
    executar(
        cpf=args.cpf,
        nascimento=args.nascimento,
        pasta_saida=Path(args.saida),
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
