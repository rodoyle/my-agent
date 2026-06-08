# Personal Coding Agent

Most agent harnesses assume 128k+ context windows, which doesn't work for offline and locally hosted agents.
Still, I am lazy and want to use these tools while disconnected.
OMLX is more than capable of sufficient tokens per second now for personal use with a Gemma or QWen class MoE model on unified RAM.

This is an experiment to pair a "local first" coding agent with OMLX for offline development.

## Concept

The core idea here is to get as much milage out of a "free but dumb" LLM as possible.
We do this in two ways.
First, use a smart-but-expensive model with online websearch capabilities to research the task and save these notes for offline reference later in on-disk "memory" rather than in-RAM "context". Sort of like a mini-RAG. 
Second, use explicit tool wrapper classes (python code) instead of markdown skill definitions to provide
the agent with targeted task, modality, and platform specific capabilities rather than letting it burn tokens trying
to "figure things out on its own". 

Instead of coaxing the agent with an ever growing heap of text skills which bloat context, tell the agent
exactly what commands it should be using.
While the former is very cool, it's neither cheap nor offline-friendly.

Examples:

- Intercepting mcp_perplexity_research calls and writing the results to filesystem instead of ingesting 10k+ tokens into context.
- Using ripgrep, fzf, fd, and bat instead of grep, find, and cat.
- Redirecting tool and mcp responses to memory not context. 
- Calling modality-specific tools like pandoc, ffmpeg, quarto, mupdf, cargo xtask, LLVM-utils, or kubectl.
- Using platform-specific tools like locate, xcode utilities, dtrace, or zsh utilities

## Candidate Frameworks

The smart-but-expensive AI (Sonnet 4.6) suggested MLX-Code and Pi-agent as the two lead contenders.
Previously testing with pi-agent had mixed results. It doesn't intercept large-response tool calls.


MLX-Code uses code instead of text to guide agent behavior.
Specifically, tool wrapper classes allow selected capabilities to be exposed.
These take the place of SKILLS.md.
More importantly, tool wrappers allow interception of massive tool results.
We can pas a brief summary to the model context and dumping the long form results to the agent's memory bank on disk.

## Usage

I deliberately made this a public github repo alongside my dotfiles repo.
The two are intended to work together.
The dotfiles repo is intended to handle installation of various tools.
This agent is intended to use them.
Both should be cloned onto a devbox -- or increasingly a devpod or cloud IDE -- to initialize a dev environment.
Secrets, keys, and credentials should be injected seperately via some sort of tool.

Eventually I may develop a branching schema to keep different environment or task contexts isolated.
