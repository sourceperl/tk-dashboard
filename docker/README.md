# docker tk-dashboard test platform

Start tk-dashboard as master:

```bash
docker-compose -f compose-master.yml up -d
```

Start tk-dashboard as slave:

```bash
docker-compose -f compose-slave.yml up -d
```

Rebuild before if some files have changed:

```bash
docker-compose -f compose-master.yml build
```

Admin the stack:

```bash
# run board-help in admin-shell to see available commands
docker attach board-admin-shell
```

