.PHONY: build up down logs restart clean start status help

help:
	@echo "Concierge Services - Makefile Commands"
	@echo ""
	@echo "  make start     - Build and start all services"
	@echo "  make up        - Start all services"
	@echo "  make down      - Stop all services"
	@echo "  make build     - Build all service images"
	@echo "  make logs      - View logs from all services"
	@echo "  make restart   - Restart all services"
	@echo "  make clean     - Stop services and remove volumes"
	@echo "  make status    - Show service status"
	@echo ""
	@echo "Services:"
	@echo "  - Context Service:  http://localhost:8080"
	@echo "  - Persona Service:   http://localhost:8081"

build:
	docker-compose build

up:
	docker-compose up -d
	@echo ""
	@echo "✓ Services started:"
	@echo "  - Context Service: http://localhost:8080"
	@echo "  - Persona Service: http://localhost:8081"

down:
	docker-compose down

logs:
	docker-compose logs -f

restart:
	docker-compose restart

clean:
	docker-compose down -v
	@echo "✓ Cleaned up all services and volumes"

start: build up
	@echo ""
	@echo "✓ All services are running!"
	@echo "  View logs with: make logs"

status:
	@docker-compose ps

