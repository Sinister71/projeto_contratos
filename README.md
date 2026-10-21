# Painel de Acompanhamento de Projetos e Demandas Técnicas

Protótipo local (sem depender de servidor da empresa) para acompanhar etapas
de projetos de TI: migração de servidores, atualização de rede, etc.

## O que tem aqui

- `database.py` — cria o banco SQLite (`projetos.db`), com as tabelas de
  projetos e de contratos, e insere dados de exemplo de projetos na primeira
  execução
- `queries.py` — consulta, cadastro, edição e KPIs das etapas de projeto
- `queries_contratos.py` — consulta, busca, cadastro, edição e KPIs dos
  contratos/atas de registro de preços
- `import_contratos.py` — importa sua planilha de contratos (.xlsx) para o
  banco de uma vez só
- `app.py` — o app Streamlit, com 4 páginas no menu lateral
- `requirements.txt` — dependências Python

## Importando sua planilha de contratos

Depois de instalar as dependências (passo 3 abaixo), rode uma vez:

```bash
python import_contratos.py Contratos_e_ARPs.xlsx
```

Isso lê a aba "GETI - Visão geral" e carrega todos os contratos/atas no
banco. Pode rodar de novo sempre que a planilha for atualizada — ele
substitui os dados antigos pelos novos (a tabela de projetos não é afetada).
O status de cada contrato (Vigente / Vencendo em breve / Vencido) é
calculado automaticamente com base na data de vencimento — não depende da
coluna "Situação" da planilha.

## Como rodar (primeira vez)

1. Instale o Python 3.10+ (se ainda não tiver): [python.org/downloads](https://www.python.org/downloads/)
2. Abra um terminal nesta pasta e crie um ambiente virtual (recomendado):

    ```bash
     python -m venv venv
     venv\Scripts\activate        # Windows
     source venv/bin/activate     # Mac/Linux
    ```

3. Instale as dependências:

    ```bash
     pip install -r requirements.txt
    ```

4. Rode o app:

  ```bash
   streamlit run app.py
   ```

   Isso abre automaticamente no navegador em `http://localhost:8501`.
   O banco `projetos.db` é criado na mesma pasta, já com 6 etapas de exemplo
   (2 projetos: migração de servidores e atualização de rede) para você ver
   o dashboard funcionando de cara. Pode apagar os exemplos e cadastrar os
   dados reais pela tela "Cadastrar / editar etapa".

## Como usar

- **Dashboard de Projetos**: KPIs (atrasadas, concluídas no mês, em
  andamento), gráfico Gantt colorido por status, carga de trabalho por
  responsável e tabela geral
- **Cadastrar / editar etapa**: formulário para adicionar novas etapas, e
  seletor para editar ou excluir uma etapa existente
- **Contratos e Licitações**: KPIs (vigentes, vencendo em até 60 dias,
  vencidos), busca por texto (fornecedor, nº do contrato, objeto, fiscal) e
  filtro por status
- **Cadastrar / editar contrato**: formulário para adicionar novos
  contratos/atas, e seletor para editar ou excluir um existente

## Para os colegas do setor acessarem também (2-3 editores)

Rode o app expondo na rede local, na mesma máquina onde ele já roda:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Depois, compartilhe `http://SEU-IP-NA-REDE:8501` com os colegas — eles
acessam pelo navegador deles, sem instalar nada. Para descobrir seu IP na
rede local: `ipconfig` (Windows) ou `ifconfig`/`ip a` (Mac/Linux).

Isso ainda não tem login/senha. Como só vai circular dentro da rede do
setor com 2-3 pessoas, pode ser aceitável no início — mas se quiser
adicionar uma senha simples depois, o pacote `streamlit-authenticator`
resolve isso em poucas linhas. Posso ajudar com isso quando chegar a hora.

## Próximos passos sugeridos

1. Trocar os dados de exemplo pelos seus projetos reais
2. Ajustar os nomes dos projetos/etapas ao seu vocabulário do setor
3. Validar sozinho por 1-2 semanas
4. Expor na rede para os colegas
5. Depois: começar o segundo projeto (Sistema de Gestão de Contratos de TI
   e Licitações), reaproveitando a mesma estrutura de banco + Streamlit
