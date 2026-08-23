from fastapi import Request

from app.application.command_context import CommandContext


def command_context(request: Request) -> CommandContext:
    return CommandContext.from_request(request)
