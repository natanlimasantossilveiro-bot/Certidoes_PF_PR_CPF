from pathlib import Path
from flask import Flask, render_template, request, send_from_directory
from main import ConsultaCpfAutomacao

BASE_DIR = Path(__file__).resolve().parent
PASTA_CERTIDOES = BASE_DIR / "certidoes"

app = Flask(__name__)

automacao = ConsultaCpfAutomacao(
    pasta_saida=PASTA_CERTIDOES,
    headless=True
)

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/iniciar")
def iniciar():
    cpf = request.form.get("cpf", "")
    nascimento = request.form.get("nascimento", "")

    try:
        automacao.iniciar(cpf, nascimento)
        arquivo = automacao.salvar_pdf()
    except Exception as erro:
        return render_template(
            "index.html",
            status="erro",
            mensagem=str(erro)
        )

    return render_template(
        "index.html",
        status="sucesso",
        mensagem="Consulta realizada com sucesso.",
        arquivo=arquivo.name
    )

@app.get("/certidoes/<nome>")
def baixar(nome):
    return send_from_directory(
        PASTA_CERTIDOES,
        nome,
        as_attachment=True
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)