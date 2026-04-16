# Automacao de certidao CPF

Automacao em Python para preencher a consulta publica de situacao cadastral do CPF na Receita Federal, aguardar a validacao manual do CAPTCHA e salvar o resultado em PDF.

## Limite sobre CAPTCHA

Este projeto nao usa 2Captcha nem outro servico para resolver CAPTCHA automaticamente. O CAPTCHA deve ser validado manualmente na janela do Chrome aberta pela automacao.

## Instalacao

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Uso com interface web

```powershell
python app.py
```

Depois abra no navegador:

```text
http://127.0.0.1:5000
```

Na pagina, informe CPF e data de nascimento, clique em `Abrir consulta`, valide o CAPTCHA na janela do Chrome e depois clique em `Salvar PDF`.

## Uso pelo terminal

```powershell
python main.py --cpf "000.000.000-00" --nascimento "01/01/1990"
```

Por padrao, o PDF sera salvo na pasta `certidoes`.

Para escolher outra pasta:

```powershell
python main.py --cpf "000.000.000-00" --nascimento "01/01/1990" --saida "C:\Certidoes"
```

## Fluxo

1. A automacao abre o Chrome na pagina da Receita Federal.
2. Preenche CPF e data de nascimento.
3. Voce marca o CAPTCHA manualmente.
4. Depois de validar o CAPTCHA, volte ao terminal e pressione Enter.
5. A consulta e enviada e o comprovante e salvo em PDF.
