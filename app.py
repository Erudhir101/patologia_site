import os
import json
import time
import threading
import requests
import markdown
from flask import Flask, request, render_template, redirect, url_for
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions

app = Flask(__name__)

# Rate limiter para a API Gemini (máximo 8 requisições por minuto)
class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            self.calls = [c for c in self.calls if now - c < self.period]
            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    print(f"DEBUG: Rate limit atingido. Aguardando {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
            self.calls.append(time.time())

_rate_limiter = RateLimiter(max_calls=8, period=60)

# Configuração do Vertex AI
CREDENTIALS_FILE = 'spry-catcher-449921-h8-bbc989e73ec4.json'
PROJECT_ID = "spry-catcher-449921-h8"
REGION = "global"  # Endpoint global reduz erros 429 por não estar preso a uma região

_genai_client = None

def init_genai_client():
    """Inicializa o cliente google-genai com as credenciais do Vertex AI."""
    global _genai_client
    if _genai_client is not None:
        return True

    try:
        # Prioridade 1: variável de ambiente com JSON (Vercel/produção)
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds_json = creds_json.strip().strip('"').strip("'")
            temp_path = "/tmp/temp_creds.json"
            try:
                creds_data = json.loads(creds_json)
                with open(temp_path, "w") as f:
                    json.dump(creds_data, f)
            except json.JSONDecodeError:
                with open(temp_path, "w") as f:
                    f.write(creds_json)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
            _genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=REGION)
            print("DEBUG: client inicializado com GOOGLE_CREDENTIALS_JSON.")
            return True

        # Prioridade 2: arquivo local de credenciais
        credentials_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CREDENTIALS_FILE)
        if os.path.exists(credentials_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            _genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=REGION)
            print(f"DEBUG: client inicializado com arquivo local: {credentials_path}")
            return True

        print(f"Erro: arquivo de credenciais não encontrado em {credentials_path}")
        return False
    except Exception as e:
        print(f"Erro crítico ao inicializar o google-genai client: {e}")
        return False

# Inicializa ao iniciar a aplicação
init_genai_client()

def get_api_data(cod_requisicao_input):
    """ Busca os dados da API externa de patologia. """
    url = "https://lab.aplis.inf.br/api/integracao.php"
    username = "api.lab"
    password = "nintendo64"
    headers = {"Content-Type": "application/json"}
    payload = {"ver": 2, "cmd": "requisicaoResultado", "dat": {"codRequisicao": cod_requisicao_input}}
    data = json.dumps(payload)

    try:
        response = requests.post(url, auth=(username, password), headers=headers, data=data, timeout=30)
        output_lines = [f"**Status Code:** `{response.status_code}`"]
        procedimentos_cobrados = []

        try:
            resposta_json = response.json()

            if not isinstance(resposta_json, dict):
                output_lines.append("Erro: Resposta da API inesperada (não é um objeto JSON).")
                return "\n\n".join(output_lines), []

            print(f"DEBUG - Resposta API para {cod_requisicao_input}:")
            print(json.dumps(resposta_json, indent=2, ensure_ascii=False))

            dat_obj = resposta_json.get("dat")
            if isinstance(dat_obj, dict) and dat_obj.get("sucesso") == 1:
                dados = dat_obj
                print(f"DEBUG - Chaves em 'dat': {list(dados.keys())}")
                output_lines.append(f"**Código da Requisição:** `{dados.get('codRequisicao', 'N/A')}`")

                procedimentos = dados.get("procedimentos", [])
                encontrou_detalhes = False

                for procedimento in procedimentos:
                    if "topografias" in procedimento:
                        for topografia in procedimento["topografias"]:
                            encontrou_detalhes = True
                            output_lines.append(f"\n### Topografia: {topografia.get('nome', '')}")
                            output_lines.append(f"**Laudo Macro:** {topografia.get('laudoMacro', '')}")

                            diagnosticos = topografia.get("diagnosticos", [])
                            for diagnostico in diagnosticos:
                                output_lines.append(f"\n> **Diagnóstico:** {diagnostico.get('titulo', '')}")
                                output_lines.append(f"> **Laudo Micro:** {diagnostico.get('laudoMicro', '')}")

                            if "cassetes" in topografia:
                                for cassete in topografia["cassetes"]:
                                    coloracoes = cassete.get("coloracoes")
                                    if coloracoes:
                                        for coloracao in coloracoes:
                                            output_lines.append(f"*   **Coloração:** {coloracao.get('nome', '')}")

                    if not encontrou_detalhes:
                        if "laudoMacro" in procedimento:
                            output_lines.append(f"\n**Laudo Macro:** {procedimento.get('laudoMacro', '')}")
                            encontrou_detalhes = True
                        if "diagnosticos" in procedimento:
                            for diagnostico in procedimento["diagnosticos"]:
                                output_lines.append(f"\n> **Diagnóstico:** {diagnostico.get('titulo', '')}")
                                output_lines.append(f"> **Laudo Micro:** {diagnostico.get('laudoMicro', '')}")
                                encontrou_detalhes = True

                procedimentos_cobrados = dados.get("procedimentosCobrados", [])

                if not encontrou_detalhes or len(output_lines) < 5:
                    output_lines.append("\n\n--- DADOS BRUTOS (FALLBACK) ---")
                    output_lines.append("A estrutura esperada não foi encontrada. Segue o JSON bruto para análise:")
                    output_lines.append(f"```json\n{json.dumps(procedimentos, indent=2, ensure_ascii=False)}\n```")

            else:
                dat_val = resposta_json.get("dat")
                if isinstance(dat_val, dict):
                    msg_erro = dat_val.get("msg", "Resposta sem sucesso ou dados inválidos.")
                else:
                    msg_erro = str(dat_val) if dat_val else "Resposta sem sucesso ou dados inválidos."
                output_lines.append(f"Erro na API: {msg_erro}")

        except (ValueError, json.JSONDecodeError):
            output_lines.append("Resposta da API não está em formato JSON válido: " + response.text)

        return "\n\n".join(output_lines), procedimentos_cobrados
    except requests.exceptions.RequestException as e:
        return f"Erro de requisição: {e}", []

def generate_ai_response(api_output_text, procedimentos_cobrados):
    """ Gera a análise da IA com base nos dados do laudo. """
    try:
        prompt_text = f"""Analise o seguinte laudo de patologia e os procedimentos cobrados pela API. Gere uma tabela Markdown com as colunas 'CodRequisicao', 'Código', 'Quantidade', seguindo as regras abaixo. Responda com a tabela Markdown, e com justificativas curtas.

Regras de Classificação e Contagem:
1.  Peça Principal: Classifique cada 'Diagnóstico' principal com base no 'LaudoMicro' e 'LaudoMacro'.Pode haver mais de uma peça principal.
    * 40601110 (Biópsia Simples): Amostra única ou até 2/frasco, < 1 cm, sem menção de margens no LaudoMicro.
    * 40601196 (Biópsia Múltiplos Fragmentos): 4+ fragmentos/frasco, < 1 cm, sem menção de margens no LaudoMicro.
    * 40601200 (Peça Cirúrgica Simples): Peças pequenas (< 3 cm, exceto mama), cistos, pólipos, pele (se principal). Até 3 margens (código 40601226) podem estar associadas.
    * 40601218 (Peça Cirúrgica Complexa): Peças médias/grandes (> 7 cm), mastectomia, gastrectomia. Até 5 margens (código 40601226) podem estar associadas.
    * Se LaudoMicro descrever "corpo e antro", classifique como dois procedimentos separados (provavelmente 40601110 ou 40601196, dependendo dos fragmentos).
2.  Peças Adicionais (40601226):
    * Margens: Se 'LaudoMicro' mencionar "margem" ou "margens" a peça principal será 40601200 ou 40601218:
        * "Margens" (plural): Conte 2x 40601226 (ou o número exato se especificado).
        * "Margem" (singular): Conte 1x 40601226.
        * Margens comprometidas, elas NÃO contam para este código.
    * Linfonodos: Contar cada linfonodo como 1x 40601226 (máximo 6 por grupo, se aplicável).
    * Lobo esquerdo ou direito
    * Dutos
3.  Colorações Especiais (40601269): Conte 1x 40601269 para cada nome de coloração listado na seção 'Coloração:' que NÃO seja 'HE' . Nomes válidos: Alcian Blue, Azul de Toluidina, Fontana-Masson, Giemsa, Gram, Grocott, Tricômio de Masson, Verheoff, Vermelho Congo.
4.  Citopatologia (se aplicável, baseado na descrição geral, não detalhado no exemplo):
    * 40601129 (Citopatológico Oncótico de Líquidos/Raspados)
    * 40601137 (Citopatologia Cervicovaginal)
5.  CodRequisicao: Use o código da requisição fornecido no texto.

Texto do Laudo:
{api_output_text}

Procedimentos Cobrados pela API (apenas para referência, não use para a sua tabela):
{json.dumps(procedimentos_cobrados, indent=2)}

Tabela Markdown de Saída (exemplo):
| CodRequisicao | Código | Quantidade |
| :--- | :--- | :--- |
| 12345 | 40601110 | 1 |
"""

        generation_config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=8192,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_ONLY_HIGH"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_ONLY_HIGH"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_ONLY_HIGH"),
            ]
        )

        max_retries = 4
        for attempt in range(max_retries):
            try:
                _rate_limiter.wait()
                response = _genai_client.models.generate_content(
                    # model="gemini-2.5-flash",
                    model="gemini-3-flash-preview",
                    contents=prompt_text,
                    config=generation_config,
                )
                ai_response_text = response.text
                break
            except google_exceptions.ResourceExhausted:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 15  # 15s, 30s, 60s
                    print(f"DEBUG: 429 ResourceExhausted (tentativa {attempt + 1}/{max_retries}). Aguardando {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

        # Formatação dos procedimentos cobrados para exibição (em Markdown)
        formatted_procedimentos_cobrados = ""
        if isinstance(procedimentos_cobrados, list):
            formatted_procedimentos_cobrados = "### Procedimentos Cobrados (API)\n\n"
            for proc in procedimentos_cobrados:
                if isinstance(proc, dict):
                    formatted_procedimentos_cobrados += (
                        f"*   **Código:** `{proc.get('codigo', '')}`\n"
                        f"*   **Descrição:** {proc.get('descricao', '')}\n"
                        f"*   **Quantidade:** {proc.get('quantidade', '')}\n"
                        f"*   **Valor Total:** R$ {proc.get('valorTotal', '')}\n\n---\n\n"
                    )
                else:
                    formatted_procedimentos_cobrados += f"*   Dado inválido: `{proc}`\n\n---\n\n"

    except Exception as e:
        ai_response_text = f"Erro ao gerar resposta da IA: {e}"
        formatted_procedimentos_cobrados = ""

    return ai_response_text, formatted_procedimentos_cobrados

@app.route('/', methods=['GET', 'POST'])
def index():
    """ Rota principal que lida com a entrada do usuário e exibe os resultados. """
    api_output = ""
    ai_output = ""
    proc_output = ""
    cod_requisicao_input = request.args.get('codrequisicao', '')

    if request.method == 'POST':
        cod_requisicao_input = request.form.get('codrequisicao', '')
        if cod_requisicao_input:
            return redirect(url_for('index', codrequisicao=cod_requisicao_input))
        else:
            api_output = "Por favor, insira o Código da Requisição."

    if cod_requisicao_input:
        api_output, procedimentos_cobrados = get_api_data(cod_requisicao_input)

        if not api_output.startswith("Erro") and "sem sucesso" not in api_output:
            init_genai_client()
            ai_output, proc_output = generate_ai_response(api_output, procedimentos_cobrados)
            api_output = markdown.markdown(api_output, extensions=['nl2br'])
            ai_output = markdown.markdown(ai_output, extensions=['tables', 'nl2br'])
            proc_output = markdown.markdown(proc_output, extensions=['nl2br'])
        else:
            ai_output = "Não foi possível gerar a análise devido a erro na busca da API."
            proc_output = ""

    return render_template('index.html',
                           api_output=api_output,
                           ai_output=ai_output,
                           proc_output=proc_output,
                           cod_requisicao_input=cod_requisicao_input)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
