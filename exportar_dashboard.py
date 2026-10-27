"""
Publica os dados dos contratos para o dashboard web (dashboard/index.html).

Gera dois arquivos na pasta `dashboard/`:

* dados_contratos.js -> `window.DADOS_CONTRATOS = {...}`. É o que o index.html carrega.
  Funciona com duplo clique no HTML (sem servidor), porque é um <script>, e não um
  fetch() de JSON (que o navegador bloqueia em arquivos locais).
* contratos.json     -> o mesmo conteúdo, para outras ferramentas (Power BI, Python...).

Princípios:

* Só FATOS vão para o arquivo (datas, valores, itens). `dias_para_vencer`, `status`
  (faixa) e `valor_global` são calculados pelo navegador na hora de abrir a página,
  então o dashboard nunca mostra prazos "congelados" no dia da exportação.
* Só os campos que o dashboard usa. Observações internas, CNPJ etc. ficam de fora.
* Contratos arquivados não são publicados.

Uso:
    python exportar_dashboard.py            # gera/atualiza os arquivos
    python exportar_dashboard.py --pasta D:\\Dashboard   # grava em outra pasta
"""

import argparse
import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd  # type: ignore

from database import DB_PATH, PASTA_PROJETO
from queries_contratos import listar_contratos
from queries_itens import listar_itens_por_contrato

PASTA_DASHBOARD = os.path.join(PASTA_PROJETO, "dashboard")
ARQUIVO_JS = "dados_contratos.js"
ARQUIVO_JSON = "contratos.json"
VERSAO_FORMATO = 1

CAMPOS_CONTRATO = (
    "id",
    "id_processo",
    "tipo",
    "numero_contrato",
    "razao_social",
    "objeto",
    "data_inicio",
    "data_fim",
    "fiscal",
)
CAMPOS_ITEM = (
    "item_numero",
    "descricao",
    "local",
    "unidade",
    "quantidade",
    "valor_mensal",
    "valor_total_item",
    "vigencia_texto",
)
CAMPOS_DATA = ("data_inicio", "data_fim")
CHAVE_CONTRATOS = "contratos"
CHAVE_ITENS = "itens"


def _valor_json(campo: str, valor):
    """Converte um valor do pandas para algo que o JSON aceite (NaN/NaT -> None)."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    if campo in CAMPOS_DATA:
        return pd.Timestamp(valor).date().isoformat()
    if hasattr(valor, "item"):  # numpy int/float -> tipo nativo do Python
        return valor.item()
    return valor


def _linha_para_dict(linha, campos: tuple) -> dict:
    return {campo: _valor_json(campo, linha[campo]) for campo in campos}


def _itens_do_contrato(contrato_id: int) -> list:
    itens = listar_itens_por_contrato(contrato_id)
    return [_linha_para_dict(linha, CAMPOS_ITEM) for _, linha in itens.iterrows()]


def montar_dados() -> dict:
    """Contratos ativos com seus itens, no formato que o dashboard espera."""
    contratos = []
    for _, linha in listar_contratos().iterrows():
        contrato = _linha_para_dict(linha, CAMPOS_CONTRATO)
        contrato[CHAVE_ITENS] = _itens_do_contrato(int(linha["id"]))
        contratos.append(contrato)
    return {
        "versao": VERSAO_FORMATO,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        CHAVE_CONTRATOS: contratos,
    }


def _gravar_atomico(caminho: str, texto: str) -> None:
    """Escreve num arquivo temporário e troca no final: o navegador nunca lê um arquivo pela metade."""
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(temporario, caminho)


def publicar_dashboard(pasta: Optional[str] = None) -> dict:
    """Gera os arquivos de dados. Devolve {'js', 'json', CHAVE_CONTRATOS, CHAVE_ITENS} (contagens)."""
    pasta = pasta or PASTA_DASHBOARD
    os.makedirs(pasta, exist_ok=True)
    dados = montar_dados()
    corpo = json.dumps(dados, ensure_ascii=False, indent=1)

    caminho_js = os.path.join(pasta, ARQUIVO_JS)
    caminho_json = os.path.join(pasta, ARQUIVO_JSON)
    _gravar_atomico(caminho_js, f"window.DADOS_CONTRATOS = {corpo};\n")
    _gravar_atomico(caminho_json, corpo + "\n")
    return {
        "js": caminho_js,
        "json": caminho_json,
        CHAVE_CONTRATOS: len(dados[CHAVE_CONTRATOS]),
        CHAVE_ITENS: sum(len(c[CHAVE_ITENS]) for c in dados[CHAVE_CONTRATOS]),
    }


def dados_desatualizados(pasta: Optional[str] = None) -> bool:
    """True se o banco foi alterado depois da última publicação (ou nunca foi publicado)."""
    caminho_js = os.path.join(pasta or PASTA_DASHBOARD, ARQUIVO_JS)
    if not os.path.isfile(caminho_js):
        return True
    return os.path.getmtime(DB_PATH) > os.path.getmtime(caminho_js)


def publicar_se_desatualizado(pasta: Optional[str] = None) -> bool:
    """Republica só quando o banco mudou. Barato de chamar a cada interação do app."""
    if not dados_desatualizados(pasta):
        return False
    publicar_dashboard(pasta)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Publica os dados do dashboard web.")
    parser.add_argument("--pasta", help="pasta de destino (padrão: dashboard/ do projeto)")
    args = parser.parse_args()
    resultado = publicar_dashboard(args.pasta)
    print(f"{resultado[CHAVE_CONTRATOS]} contratos e {resultado[CHAVE_ITENS]} itens publicados em:")
    print(f"  {resultado['js']}")
    print(f"  {resultado['json']}")


if __name__ == "__main__":
    main()
