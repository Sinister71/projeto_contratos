# Painel de TI — Contratos, Pedidos e Projetos

Sistema local (sem depender de servidor da empresa) feito em Python, Streamlit
e SQLite para acompanhar contratos, atas de registro de preços (ARPs), itens
de contratos, pedidos e projetos da área de TI, com um dashboard web (Vue)
alimentado pelos mesmos dados.

## Arquivos

- `app.py` — o app Streamlit (menu lateral, páginas, backup e dashboard web)
- `painel.py` — Painel Geral (gráficos, Gantt) e página do Resumo Semanal
- `resumo_semanal.py` — monta o resumo semanal e gera Excel / HTML / texto
- `gerar_resumo_semanal.py` — script agendável: resumo + backup semanal + dashboard
- `import_contratos.py` — importa a planilha de contratos (.xlsx)
- `backup.py` — backup do banco (manual, antes de importar e semanal)
- `exportar_dashboard.py` — publica os dados do dashboard web
- `dashboard/index.html` — o dashboard web (Vue 3, Tailwind, Chart.js, Lucide)
- `database.py` — banco SQLite (`projetos.db`) e criação das tabelas
- `queries_contratos.py`, `queries_itens.py`, `queries_pedidos.py`,
  `queries.py` — acesso aos dados
- `requirements.txt` — dependências Python

## Como rodar

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`. Para os colegas acessarem pela rede:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Backup do banco

Todos os dados ficam no arquivo `projetos.db`. Faça backup com frequência.

- **Pelo app:** barra lateral > **💾 Backup do banco** > *Fazer backup agora*.
  O app avisa quando o último backup tem mais de 7 dias. Você pode informar uma
  pasta extra (pasta de rede, OneDrive) para receber uma cópia, e baixar a cópia.
- **Pelo terminal:** `python backup.py` (opções `--pasta` e `--manter`).
- **Automático:** o backup é feito sozinho **antes de cada importação** e a cada
  execução do `gerar_resumo_semanal.py`. As cópias ficam em `backups/`, com a
  data e o motivo no nome, e só as 30 mais recentes de cada tipo são mantidas.

Copiar o `projetos.db` pelo Explorer também funciona, desde que o app esteja
fechado. O backup do `backup.py` usa a API do próprio SQLite, então sai
consistente mesmo com o app aberto, e cada cópia é verificada antes de ser aceita.

Guarde também uma cópia **fora deste computador**: backup só na mesma máquina
não protege contra falha de disco.

Para restaurar:

1. feche o app;
2. renomeie o `projetos.db` atual (guarde-o);
3. copie a cópia desejada de `backups/` para a pasta do projeto com o nome
   `projetos.db`.

## Atualizando a planilha de contratos

```bash
python import_contratos.py Contratos_e_ARPs.xlsx
```

Rode sempre que a planilha mudar. As regras:

- **Identidade do contrato = tipo + nº do contrato** (ex.: "Contrato 115-2025").
  O ID do processo não é chave porque muda a cada renovação.
- Contrato que já existe é **atualizado** com o que mudou na planilha. Itens e
  observações são preservados, inclusive em renovações.
- **O que você editou no sistema é protegido.** Se um campo do sistema for
  diferente do que a planilha dizia na última importação, ele é mantido e a
  importação apenas avisa que a planilha está diferente. Exemplo: você renovou o
  172-2025 à mão antes de a planilha ser atualizada. O aviso some sozinho quando
  a planilha passar a dizer o mesmo que o sistema. Se a planilha trouxer outra
  data, o sistema continua valendo e o aviso se repete.
- Para a planilha **sobrescrever tudo**, inclusive suas edições:
  `python import_contratos.py Contratos_e_ARPs.xlsx --forcar-planilha`.
- Contrato novo é **inserido**.
- Contrato que **saiu da planilha** é **arquivado**, não apagado: some do
  painel e dos resumos, mas os itens continuam guardados. Se voltar à planilha,
  é reativado sozinho.
- Contrato que **você** arquivou à mão continua arquivado. Contrato que a
  importação arquivou e você reativou à mão passa a ser "seu" e não é arquivado
  de novo. Contratos cadastrados à mão em "Cadastros" nunca são arquivados.
- Linhas repetidas do mesmo contrato na planilha (ex.: uma do processo de
  renovação ainda sem datas) são unificadas: vale a de vencimento mais recente.
- Antes de gravar, é feito um backup automático (`--sem-backup` desliga).

Na **primeira** importação depois de atualizar o sistema ainda não existe o
histórico "o que a planilha dizia da última vez". Nessa vez, qualquer diferença
entre o sistema e a planilha é tratada como edição sua e fica protegida.

## Dashboard web

O dashboard (`dashboard/index.html`) é uma página estática que **lê os dados
publicados pelo sistema**. O Streamlit continua sendo o único lugar onde os
dados são editados.

- Os dados vão para `dashboard/dados_contratos.js` (usado pela página) e
  `dashboard/contratos.json` (o mesmo conteúdo, para outras ferramentas).
- São republicados **sozinhos** a cada alteração feita no app, depois de cada
  importação e a cada execução do resumo semanal. Em *Dashboard web* na barra
  lateral há também o botão *Atualizar agora*.
- Para abrir: dê um duplo clique em `dashboard/index.html`. Funciona sem servidor.
  Para compartilhar, coloque a pasta `dashboard/` em uma pasta de rede ou sirva
  com `python -m http.server 8080 --directory dashboard`.
- Os arquivos de dados trazem só fatos (datas, valores, itens). Prazo em dias,
  faixa de vencimento e valor global são calculados pelo navegador ao abrir a
  página, então o dashboard nunca mostra prazos desatualizados.
- O dashboard não recebe observações internas nem CNPJ. Quem tiver o arquivo
  vê os valores dos contratos: trate a pasta com o mesmo cuidado do banco.
- O **custo mensal recorrente** soma só itens com unidade "Mensal". Nos demais
  itens (Unidade, Documento, Mensagem...) a coluna `valor_mensal` guarda o preço
  unitário, que não é custo mensal.
- Sem o arquivo de dados, a página mostra dados de exemplo e avisa no cabeçalho.
- As bibliotecas (Vue, Tailwind, Chart.js, Lucide) vêm de CDN: o computador que
  abrir a página precisa de internet.

## Menu

- **📊 Painel Geral** (tela inicial): vencidos e a vencer em 30 / 60 / 90 dias,
  Gantt dos contratos que vencem primeiro, fiscais, fornecedores, pedidos de
  cada ARP e pendências de cadastro
- **📋 Resumo Semanal**: contratos nas faixas, o que mudou de faixa nos últimos
  7 dias, o que vence em 7 dias e o resumo por fiscal. Baixe em Excel, HTML ou
  texto, ou copie a mensagem pronta (Teams, e-mail, WhatsApp)
- **📄 Contratos e Licitações**: busca, filtro por status e botão "Ver itens"
- **📄 Itens do Contrato**: itens de cada contrato (nº automático; valor global
  é a soma dos itens)
- **📦 Controle de Pedidos**: restante em dias calculado, filtro por ARP e
  situação "Atrasado" automática
- **✏️ Cadastros**: contratos/ARPs, pedidos e etapas de projeto
- **📁 Projetos**: dashboard de etapas de projetos

## Agendamentos (Windows)

A tela **Resumo Semanal** mostra, em "Receber automaticamente toda semana", o
comando pronto com os caminhos do seu computador. Ele agenda o
`gerar_resumo_semanal.py` toda segunda-feira às 08:00. Cada execução gera o
resumo em `resumos/`, faz o backup semanal e atualiza os dados do dashboard. O
computador precisa estar ligado no horário.

Também dá para rodar na mão:

```bash
python gerar_resumo_semanal.py
python gerar_resumo_semanal.py --pasta \\servidor\pasta
python gerar_resumo_semanal.py --simular 2026-12-01
python gerar_resumo_semanal.py --sem-backup
```

## Observações

- Os status (vencido, até 30 dias, etc.) são recalculados todo dia a partir da
  data de vencimento; não dependem da coluna "Situação" da planilha.
- Ainda não há login/senha. Se for expor na rede, vale adicionar autenticação
  (por exemplo, `streamlit-authenticator`)
