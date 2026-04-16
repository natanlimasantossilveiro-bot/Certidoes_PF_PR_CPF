from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from flask import Flask, render_template, request, send_from_directory

from main import ConsultaCpfAutomacao


BASE_DIR = Path(__file__).resolve().parent
PASTA_CERTIDOES = BASE_DIR / "certidoes"

app = Flask(__name__)
automacao = ConsultaCpfAutomacao(pasta_saida=PASTA_CERTIDOES, headless=False)
consulta_em_andamento = False
consulta_tempo_inicio = None
TIMEOUT_CONSULTA = 300  # 5 minutos em segundos
consulta_lock = Lock()


def fechar_automacao() -> None:
    try:
        automacao.fechar()
    except Exception:
        pass


@app.get("/")
def index():
    if consulta_em_andamento:
        return render_template(
            "index.html",
            status="captcha",
            mensagem=(
                "Existe uma consulta em andamento. Continue no Chrome aberto "
                "ou cancele para iniciar outra consulta."
            ),
        )

    return render_template("index.html", status=None)


@app.post("/iniciar")
def iniciar():
    global consulta_em_andamento, consulta_tempo_inicio

    cpf = request.form.get("cpf", "")
    nascimento = request.form.get("nascimento", "")

    with consulta_lock:
        # Verifica se timeout expirou
        if consulta_em_andamento and consulta_tempo_inicio:
            tempo_decorrido = (datetime.now() - consulta_tempo_inicio).total_seconds()
            if tempo_decorrido > TIMEOUT_CONSULTA:
                print(f"Timeout de {TIMEOUT_CONSULTA}s expirou. Resetando...")
                fechar_automacao()
                consulta_em_andamento = False
        
        if consulta_em_andamento:
            return render_template(
                "index.html",
                status="erro",
                mensagem="Ja existe uma consulta em andamento. Cancele ou reinicie o app.",
            )

        try:
            automacao.iniciar(cpf=cpf, nascimento=nascimento)
        except Exception as erro:
            fechar_automacao()
            return render_template("index.html", status="erro", mensagem=str(erro))

        consulta_em_andamento = True
        consulta_tempo_inicio = datetime.now()
    return render_template(
        "index.html",
        status="captcha",
        mensagem=(
            "Chrome aberto e dados preenchidos. Na janela do Chrome, valide o "
            "CAPTCHA e clique em Consultar. Quando o comprovante aparecer, volte "
            "aqui e clique em Salvar PDF."
        ),
    )


@app.post("/salvar")
def salvar():
    global consulta_em_andamento

    with consulta_lock:
        try:
            arquivo_pdf = automacao.consultar_e_salvar()
        except Exception as erro:
            fechar_automacao()
            consulta_em_andamento = False
            return render_template("index.html", status="erro", mensagem=str(erro))

        consulta_em_andamento = False
    if not arquivo_pdf.exists():
        return render_template(
            "index.html",
            status="erro",
            mensagem=f"O PDF foi gerado, mas nao foi encontrado em: {arquivo_pdf}",
        )

    return render_template(
        "index.html",
        status="sucesso",
        mensagem=f"PDF salvo em: {arquivo_pdf}",
        arquivo=arquivo_pdf.name,
    )


@app.post("/status")
def status():
    with consulta_lock:
        urls = automacao.urls_abertas()
        if not urls:
            mensagem = "Nenhuma janela da Receita esta aberta pela automacao."
        else:
            mensagem = "Paginas abertas na automacao: " + " | ".join(urls)

        return render_template(
            "index.html",
            status="captcha" if consulta_em_andamento else None,
            mensagem=mensagem,
        )


@app.post("/cancelar")
def cancelar():
    global consulta_em_andamento

    with consulta_lock:
        fechar_automacao()
        consulta_em_andamento = False
    return render_template("index.html", status=None, mensagem="Consulta cancelada.")


@app.get("/certidoes/<nome_arquivo>")
def baixar(nome_arquivo):
    # Proteção contra path traversal
    if ".." in nome_arquivo or nome_arquivo.startswith("/"):
        return render_template("index.html", status="erro", mensagem="Arquivo invalido."), 400
    return send_from_directory(PASTA_CERTIDOES, nome_arquivo, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=False)
