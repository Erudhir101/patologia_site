import os
import json
import requests
import markdown
from flask import Flask, request, render_template, redirect, url_for
import vertexai
from vertexai.generative_models import GenerativeModel, Part, Content, GenerationConfig, SafetySetting

app = Flask(__name__)

# Configuração do Vertex AI
# Certifique-se de que o arquivo de credenciais esteja na raiz do projeto ou configure a variável de ambiente corretamente.
CREDENTIALS_FILE = 'spry-catcher-449921-h8-bbc989e73ec4.json'
PROJECT_ID = "spry-catcher-449921-h8"
REGION = "us-central1"

_vertex_initialized = False

def init_vertex_ai():
    """Inicializa o Vertex AI com as credenciais."""
    global _vertex_initialized
    if _vertex_initialized:
        return True

    try:
        # Tenta carregar de variável de ambiente (Seguro para Vercel)
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            print("DEBUG: GOOGLE_CREDENTIALS_JSON encontrada.")
            creds_json = creds_json.strip()
            # Remove aspas se a string estiver envolvida por elas (comum em alguns ambientes)
            if (creds_json.startswith('"') and creds_json.endswith('"')) or \
               (creds_json.startswith("'") and creds_json.endswith("'")):
                creds_json = creds_json[1:-1]
            
            # No Vercel, apenas o diretório /tmp é gravável
            temp_path = "/tmp/temp_creds.json"
            
            try:
                # Tenta carregar para validar se é JSON válido
                creds_data = json.loads(creds_json)
                with open(temp_path, "w") as f:
                    json.dump(creds_data, f)
                print("DEBUG: JSON de credenciais validado e salvo em /tmp/temp_creds.json")
            except json.JSONDecodeError as e:
                print(f"DEBUG: Erro ao decodar JSON: {e}")
                # Se houver "Extra data", extrai apenas a parte válida
                if "Extra data" in str(e) and hasattr(e, 'pos'):
                    try:
                        valid_json = creds_json[:e.pos].strip()
                        creds_data = json.loads(valid_json)
                        with open(temp_path, "w") as f:
                            json.dump(creds_data, f)
                        print(f"DEBUG: JSON parcial validado (pos {e.pos})")
                    except:
                        with open(temp_path, "w") as f:
                            f.write(creds_json)
                else:
                    with open(temp_path, "w") as f:
                        f.write(creds_json)

            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
            vertexai.init(project=PROJECT_ID, location=REGION)
            _vertex_initialized = True
            print("DEBUG: Vertex AI inicializado com variável de ambiente.")
            return True

        # Fallback para o arquivo local
        base_dir = os.path.dirname(os.path.abspath(__file__))
        credentials_path = os.path.join(base_dir, CREDENTIALS_FILE)

        if os.path.exists(credentials_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            vertexai.init(project=PROJECT_ID, location=REGION)
            _vertex_initialized = True
            print(f"DEBUG: Vertex AI inicializado com arquivo local: {credentials_path}")
            return True
        else:
            print(f"Aviso: Arquivo de credenciais não encontrado em {credentials_path}")
            return False
    except Exception as e:
        print(f"Erro crítico ao inicializar o Vertex AI: {e}")
        return False
# Inicializa ao iniciar a aplicação
init_vertex_ai()

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
            
            # Garante que a resposta seja um dicionário
            if not isinstance(resposta_json, dict):
                output_lines.append(f"Erro: Resposta da API inesperada (não é um objeto JSON).")
                return "\n\n".join(output_lines), []

            # Debug: Imprimir resposta bruta no console para verificação
            print(f"DEBUG - Resposta API para {cod_requisicao_input}:")
            print(json.dumps(resposta_json, indent=2, ensure_ascii=False))

            dat_obj = resposta_json.get("dat")
            if isinstance(dat_obj, dict) and dat_obj.get("sucesso") == 1:
                dados = dat_obj
                print(f"DEBUG - Chaves em 'dat': {list(dados.keys())}")
                output_lines.append(f"**Código da Requisição:** `{dados.get('codRequisicao', 'N/A')}`")

                procedimentos = dados.get("procedimentos", [])

                # Variável para rastrear se encontramos dados detalhados
                encontrou_detalhes = False

                for procedimento in procedimentos:
                    # 1. Tenta extrair de 'topografias' (Estrutura Padrão)
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

                    # 2. Fallback: Tenta procurar chaves direto no procedimento (caso a estrutura mude)
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

                # 3. Fallback Final: Se não extraiu quase nada, anexa o JSON bruto dos procedimentos
                # Isso garante que a IA receba o texto mesmo se nossa lógica de chaves estiver errada
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
        model_name = "gemini-2.5-flash"
        genai_model = GenerativeModel(model_name)

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

        contents = [Content(role="user", parts=[Part.from_text(text=prompt_text)])]
        generation_config = GenerationConfig(temperature=0.2, max_output_tokens=8192)
        safety_settings = [
            SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_ONLY_HIGH"),
            SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_ONLY_HIGH"),
            SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_ONLY_HIGH"),
            SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_ONLY_HIGH")
        ]

        responses = genai_model.generate_content(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
            stream=False,
        )

        # Acesso seguro à resposta
        if hasattr(responses, 'candidates') and len(responses.candidates) > 0:
            candidate = responses.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                ai_response_text = candidate.content.parts[0].text
            else:
                ai_response_text = "IA não gerou conteúdo de resposta."
        else:
            ai_response_text = "Resposta sem candidatos do Vertex AI."

        # Formatação dos procedimentos cobrados para exibição (em Markdown)
        formatted_procedimentos_cobrados = ""
        if isinstance(procedimentos_cobrados, list):
            formatted_procedimentos_cobrados = "### Procedimentos Cobrados (API)\n\n"
            for proc in procedimentos_cobrados:
                # Verifica se proc é um dicionário antes de chamar .get()
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
            # Inicializa Vertex AI se necessário (caso não tenha inicializado no começo)
            init_vertex_ai()
            ai_output, proc_output = generate_ai_response(api_output, procedimentos_cobrados)
            # Converte as respostas de Markdown para HTML
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
