# Kaystant API

Backend isolado do protótipo em `neocities/test/`. Usa apenas tabelas `kt_*`, sem tocar nas tabelas `kp_*` da KayePad.

## Ativação

1. Execute `schema.sql` no projeto PostgreSQL do Supabase.
2. Crie um serviço separado no Render usando `kaystant-render.yaml` ou configure:
   - `DATABASE_URL`: conexão PostgreSQL do Supabase;
   - `JWT_SECRET`: segredo gerado pelo Render;
   - `CORS_ORIGINS`: origem do site estático.
3. Defina no HTML, antes de `app.js`:

```html
<script>window.KAYSTANT_API='https://SEU-SERVICO.onrender.com'</script>
```

O front-end continua funcionando em modo demonstração enquanto essa variável não existir. Quando configurada, o feed tenta carregar dados reais da API.

## Núcleo implementado

- cadastro, login e sessões opacas;
- perfis com cor de tinta, bio e banner;
- publicações por categoria;
- tinta única por usuário em cada publicação;
- frasco com meta e resgate único de 0–15 coins;
- loja de Caneta, Régua e Selo;
- proteção contra auto-tinta e saldo negativo;
- CORS limitado e persistência PostgreSQL.

## Segunda camada implementada

- pet único por perfil, com nome, cor, formato e contador de carinho;
- endpoint público para visualizar pet e endpoint autenticado de carinho;
- grupos com Régua, hashtag, regras, imagem e limite de 10 membros;
- livros com Caneta, seleção de artigos próprios e destaque automático por 3 dias;
- endpoint de destaques ativos para o feed;
- tabelas adicionais `kt_*`, sempre isoladas das tabelas `kp_*`.

Endpoints principais: `PUT /me/pet`, `GET /users/{username}/pet`, `POST /pets/{id}/affection`, `POST /groups`, `GET /groups`, `POST /groups/{id}/join`, `POST /books`, `GET /books` e `GET /highlights`.
