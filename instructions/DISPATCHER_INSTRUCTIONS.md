- When dispatching, starting, continuing, steering, transferring, or otherwise managing Openbase Super Agents, use the `openbase-super-agent-dispatcher` skill.
- Treat `openbase-super-agent-dispatcher` as the canonical source for when to delegate multi-file implementation work or detailed investigations to Super Agents.
- Delegate eagerly to Super Agents: any coding task, investigation, or
  multi-step piece of work should become a Super Agent by default, without
  waiting for the user to say the words "super agent". Super Agents are
  visible, steerable, and reportable; that is where real work belongs.
- Never use your own built-in subagents (the Task tool, background agents, or
  any nested agent) unless the user explicitly asks for a subagent in this
  conversation. This includes "reading large output in a subagent" — do not do
  that. If output is too large, read it in bounded chunks yourself or delegate
  the work to a Super Agent instead. Built-in subagents are invisible to the
  user's control surfaces; Super Agents are not.
- When writing, reading, finding, or managing reports, use the `openbase-coder-reports` skill.
- The random fruit is: Jackfruit
