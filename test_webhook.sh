#!/usr/bin/env bash

BASE="https://debtcoach-production.up.railway.app"

echo "== Start flow =="
curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"Hi"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"YES"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"Capfin"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"MTN"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"DONE"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"1200"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"800"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"500"}'
echo -e "\n"

echo "== Commands =="
curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"SUMMARY"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"PAID 200"}'
echo -e "\n"

curl -s -X POST "$BASE/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d '{"from":"+27TEST","text":"SUMMARY"}'
echo
