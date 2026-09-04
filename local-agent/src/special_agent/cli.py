import asyncio

from . import agent


def main():
    asyncio.run(agent.run())
