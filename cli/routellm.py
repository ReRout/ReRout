#!/usr/bin/env python3
"""
RouteLLM CLI - Minimal chat helper for MVP
Usage: routellm -m <model> "<prompt>"
"""
import os
import sys
import json
import click
import httpx


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--model", "model", "-m", required=True, help="Model (provider/model or alias)")
@click.argument("prompt", nargs=-1, required=True)
def chat(model: str, prompt: str) -> None:
    base_url = os.getenv("ROUTELLM_URL", "http://localhost:8084")
    text = " ".join(prompt)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
    }

    try:
        resp = httpx.post(f"{base_url}/v1/chat/completions", json=payload, timeout=60.0)
    except httpx.RequestError as e:
        click.echo(f"Request error: {e}", err=True)
        sys.exit(1)

    if resp.status_code >= 400:
        try:
            err = resp.json()
        except json.JSONDecodeError:
            err = {"error": {"message": resp.text}}
        click.echo(json.dumps(err, indent=2), err=True)
        sys.exit(1)

    data = resp.json()
    # Best-effort extract content (OpenAI-style)
    content = None
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        content = json.dumps(data, indent=2)
    click.echo(content)


if __name__ == "__main__":
    cli()
