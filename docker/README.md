# start docker stack

Start tk-dashboard for Loos master:

```bash
./loos-master-compose up -d
```

With rebuild if some files have changed:

```bash
./loos-master-compose up -d --build
```

Admin the stack:

```bash
# run board-help in admin-shell to see available commands
docker exec -it board-admin-shell bash
```
