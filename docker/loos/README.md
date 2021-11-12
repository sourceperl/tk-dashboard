# docker tk-dashboard Loos platform

Start tk-dashboard as master:

```bash
docker-compose -f master-compose.yml up -d
```

Start tk-dashboard as slave:

```bash
docker-compose -f slave-compose.yml up -d
```

With rebuild if some files have changed:

```bash
docker-compose -f master-compose.yml up -d --build
```

Admin the stack:

```bash
# run board-help in admin-shell to see available commands
docker exec -it board-admin-shell bash
```
