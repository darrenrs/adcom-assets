#!/bin/bash

docker network inspect adcom-sites >/dev/null 2>&1 || docker network create adcom-sites

docker compose up --build -d --remove-orphans
