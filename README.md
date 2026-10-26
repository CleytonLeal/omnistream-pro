# ⚡ OmniStream PRO • Guia de Deploy para Hospedagem

Pacote de produção do **OmniStream PRO**, o aplicativo web universal para download e extração de vídeos em alta resolução (4K, 1080p, MP3) de mais de 1.750 plataformas (YouTube, TikTok sem marca d'água, Instagram Reels, Twitch, Twitter/X, Vimeo, etc.).

Esta pasta foi estruturada especificamente para subir para serviços de hospedagem em nuvem (PaaS, VPS, Docker) sem arquivos desnecessários ou pesados.

---

## 📁 Estrutura do Projeto

```text
omnistream-pro/
├── templates/
│   └── index.html          # Interface mobile-first (i18n, app shell, dark mode, player)
├── downloads/              # Pasta onde os vídeos são salvos
│   └── .gitkeep
├── web_app.py              # Aplicação Flask e rotas da API REST
├── wsgi.py                 # Ponto de entrada de produção para servidores WSGI
├── downloader.py          # Motor yt-dlp resiliente com FFmpeg automático
├── background_worker.py    # Fila de tarefas em segundo plano e telemetria
├── config.py               # Configurações e detecção de caminhos
├── config.json             # Padrões de execução
├── rpa_engine.py           # Processamento em lote e vigilante
├── requirements.txt        # Dependências Python (Flask, yt-dlp, gunicorn, waitress)
├── Dockerfile              # Imagem Docker com Linux Debian e FFmpeg pré-instalado
├── docker-compose.yml      # Orquestração local/servidor com volume persistente
├── Procfile                # Comando de inicialização para Render, Railway e Heroku
├── render.yaml             # Blueprint de deploy em 1 clique no Render
├── .gitignore              # Ignora arquivos temporários, vídeos e cache
└── .env.example            # Exemplo de variáveis de ambiente
```

---

## 🚀 Opção 1: Deploy Gratuito no Render (Recomendado)

O [Render.com](https://render.com) oferece hospedagem web gratuita e lê automaticamente as configurações deste projeto.

1. Crie uma conta no [Render.com](https://render.com).
2. Suba esta pasta para um repositório no seu **GitHub** ou **GitLab**.
3. No painel do Render:
   - Clique em **New +** e selecione **Web Service**.
   - Conecte seu repositório do GitHub.
4. Preencha as configurações:
   - **Environment**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --workers=1 --threads=4 --timeout=180 --bind=0.0.0.0:$PORT wsgi:app`
5. Clique em **Create Web Service**. O Render instalará as dependências e criará o link público (ex: `https://seu-app.onrender.com`).

> **Dica:** O Render detecta o arquivo `render.yaml` e `Procfile` automaticamente.

---

## 🚂 Opção 2: Deploy no Railway.app

O [Railway.app](https://railway.app) detecta o `Dockerfile` automaticamente:

1. Crie uma conta no [Railway.app](https://railway.app).
2. Clique em **New Project** -> **Deploy from GitHub repo**.
3. Selecione o repositório do OmniStream.
4. O Railway detectará o `Dockerfile` com FFmpeg e iniciará a compilação.
5. Em **Settings** -> **Networking**, clique em **Generate Domain** para gerar o link público HTTPS.

---

## 🐳 Opção 3: Deploy com Docker (Qualquer Servidor VPS)

Ideal para servidores VPS (Ubuntu / Debian na DigitalOcean, Hetzner, AWS, Linode, Hostinger):

1. Clone o repositório na sua VPS:
   ```bash
   git clone <URL_DO_SEU_REPOSITORIO>
   cd omnistream-pro
   ```

2. Inicie o container com Docker Compose:
   ```bash
   docker compose up -d --build
   ```

3. Pronto! O app estará rodando na porta `5000` com FFmpeg integrado e volume persistente para os downloads.

---

## 💻 Opção 4: Execução Local em Desenvolvimento

```bash
# 1. Criar e ativar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # No Linux/Mac
# ou no Windows: .\.venv\Scripts\activate

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Rodar aplicação
python web_app.py
```
Acesse no navegador: `http://127.0.0.1:5000`

---

## ⚙️ Variáveis de Ambiente Suportadas

| Variável | Padrão | Descrição |
| :--- | :--- | :--- |
| `PORT` | `5000` | Porta onde o servidor HTTP escuta |
| `HOST` | `0.0.0.0` | IP de escuta (em produção usa `0.0.0.0`) |
| `DOWNLOAD_DIR` | `downloads` | Diretório de armazenamento das mídias |
| `DEFAULT_QUALITY` | `best` | Qualidade padrão de download |
| `CONCURRENT_FRAGMENTS` | `4` | Fragmentos simultâneos para vídeos longos |
| `MIN_FREE_SPACE_GB` | `1.0` | Espaço mínimo em disco antes de pausar |
