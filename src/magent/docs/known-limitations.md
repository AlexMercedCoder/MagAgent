# Known Limitations

- Provider support is qualified per provider and model. Catalog presence does not prove live
  completion, streaming, tool use, or subscription compatibility.
- The deterministic offline eval suite exercises the real AgentSession and native tools, but
  it does not measure a model's planning quality. Live provider qualification remains required.
- Browser, gateway, desktop, and remote MCP behavior depends on optional dependencies and
  external services. Core CI uses local fakes and protocol fixtures where possible.
- MCP Tasks, remote Skills, and Apps rendering remain experimental until their conformance
  gates pass. Classic stdio and modern Streamable HTTP are the supported core transports.
- MagAgent is pre-1.0. Stable contracts follow the documented deprecation policy; beta and
  experimental contracts can change in a minor release with migration notes.
- A release evidence report is a snapshot. It does not replace reviewing unresolved issues,
  upstream outages, platform-specific behavior, or the release's documented exceptions.
- The 0.70.0 suite passes 777 tests at 67.73% branch-aware coverage, below the roadmap's 72%
  target. The enforced 64% regression floor passes; gateway routing and artifact execution
  remain the highest-priority security-adjacent coverage gaps at 76% each.
