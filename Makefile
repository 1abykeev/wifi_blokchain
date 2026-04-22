# Run these commands from Git Bash (comes with Git for Windows) or WSL.
# Docker Desktop for Windows must be running.

IMAGE     = blockchain-wifi
CONTAINER = blockchain-wifi-app
VOLUME    = blockchain-wifi-data
PORT      = 5000

.PHONY: build run stop restart logs shell clean

build:
	docker build -t $(IMAGE) .

run: stop
	docker run -d \
		--name $(CONTAINER) \
		-p $(PORT):5000 \
		-v $(VOLUME):/app/data \
		-e SIMULATION_MODE=True \
		-e FLASK_HOST=0.0.0.0 \
		-e FLASK_PORT=5000 \
		-e FLASK_DEBUG=False \
		-e AUTO_MINE=True \
		$(IMAGE)
	@echo ""
	@echo "  Admin dashboard : http://localhost:$(PORT)/admin"
	@echo "  Client chat UI  : http://localhost:$(PORT)/client"
	@echo "  REST API base   : http://localhost:$(PORT)/api"
	@echo ""

stop:
	-docker stop $(CONTAINER) 2>/dev/null || true
	-docker rm   $(CONTAINER) 2>/dev/null || true

restart: stop run

logs:
	docker logs -f $(CONTAINER)

shell:
	docker exec -it $(CONTAINER) /bin/bash

# Removes the container, image, AND the persistent data volume
clean: stop
	-docker rmi $(IMAGE) 2>/dev/null || true
	-docker volume rm $(VOLUME) 2>/dev/null || true

.DEFAULT_GOAL := run
