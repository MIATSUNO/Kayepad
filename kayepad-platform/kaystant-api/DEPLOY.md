# Implantação isolada

Este serviço pode coexistir com `kayepad-api` no mesmo projeto Supabase: o schema do Kaystant usa exclusivamente `kt_*`.

## Supabase

```bash
psql "$KAYSTANT_DATABASE_URL" -f schema.sql
```

Use uma variável própria (`KAYSTANT_DATABASE_URL`) para não reutilizar acidentalmente configurações do serviço principal.

## Render

Crie um segundo Web Service com `kaystant-render.yaml`, mantendo o serviço `kayepad-api` intacto. Configure `DATABASE_URL` apontando para o mesmo banco somente se quiser compartilhar a instância; as tabelas continuam isoladas pelo prefixo.

Depois de obter a URL do serviço, acrescente no HTML do site estático:

```html
<script>window.KAYSTANT_API='https://kaystant-api.onrender.com'</script>
```

Substitua pelo endereço real gerado pelo Render; não use esse domínio como URL presumida.
