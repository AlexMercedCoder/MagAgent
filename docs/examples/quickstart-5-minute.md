# Five Minute MagAgent Check

Use this when you want a fast confidence pass on a new install or provider.

```bash
magent readiness
magent provider models opencode-go
magent provider tool-smoke opencode-go --model deepseek-v4-flash
magent ask --repair-attempts 1 "Create hello.txt containing hello from MagAgent"
```

For Nous Portal, prefer the namespaced cheap model:

```bash
magent provider models nous-portal --refresh
magent provider tool-smoke nous-portal --model deepseek/deepseek-v4-flash
```

Review the accumulated observations with:

```bash
magent model health
magent model recommend --provider nous-portal
```
