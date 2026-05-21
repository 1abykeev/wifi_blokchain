# Run these commands from Git Bash (comes with Git for Windows) or WSL.
# Docker Desktop for Windows must be running.

PORT = 5000

.PHONY: build run down stop restart logs shell clean

build:
	docker compose build

run:
	docker compose up -d
	@echo ""
	@echo "  Admin dashboard : http://localhost:$(PORT)/admin"
	@echo "  Client chat UI  : http://localhost:$(PORT)/client"
	@echo "  REST API base   : http://localhost:$(PORT)/api"
	@echo ""

down:
	docker compose down

stop: down

restart: down run

logs:
	docker compose logs -f

shell:
	docker compose exec app /bin/bash

# Removes containers, image, AND the persistent data volume
clean: down
	docker compose down --rmi all --volumes

.DEFAULT_GOAL := run
