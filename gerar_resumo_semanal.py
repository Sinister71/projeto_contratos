"""
Gera o resumo semanal de contratos (Excel + HTML + texto) na pasta `resumos/`.

Rodar manualmente:
    python gerar_resumo_semanal.py

Para rodar sozinho toda semana, agende no Windows (veja a tela "Resumo Semanal"
do app, que mostra o comando pronto com os caminhos do seu computador).

Além do resumo, faz o backup semanal do banco (pasta backups/) e atualiza os dados
do dashboard web (pasta dashboard/).

Opções:
    --pasta CAMINHO   salva em outra pasta (ex.: uma pasta de rede da gerência)
    --simular AAAA-MM-DD   gera o resumo como se hoje fosse essa data (para testes)
    --sem-backup      não faz o backup semanal do banco
"""

import argparse

from backup import MOTIVO_SEMANAL, fazer_backup
from database import inicializar_banco
from exportar_dashboard import CHAVE_CONTRATOS, CHAVE_ITENS, publicar_dashboard
from resumo_semanal import gerar_texto, montar_resumo, salvar_arquivos


def main():
    parser = argparse.ArgumentParser(description="Gera o resumo semanal de contratos.")
    parser.add_argument("--pasta", help="pasta onde salvar os arquivos (padrão: resumos/)")
    parser.add_argument("--simular", help="data fictícia de hoje, no formato AAAA-MM-DD")
    parser.add_argument("--sem-backup", action="store_true", help="não faz o backup semanal do banco")
    args = parser.parse_args()

    if not args.sem_backup:
        print(f"Backup semanal: {fazer_backup(motivo=MOTIVO_SEMANAL)}")

    inicializar_banco()
    resumo = montar_resumo(hoje=args.simular)
    caminhos = salvar_arquivos(resumo, args.pasta)

    print(gerar_texto(resumo))
    print("\nArquivos gerados:")
    for caminho in caminhos.values():
        print(f"  {caminho}")

    publicado = publicar_dashboard()
    print(f"\nDashboard web atualizado: {publicado[CHAVE_CONTRATOS]} contratos, {publicado[CHAVE_ITENS]} itens.")


if __name__ == "__main__":
    main()