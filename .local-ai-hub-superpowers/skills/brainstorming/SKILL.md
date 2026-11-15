---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, modifying behavior, or planning anything new, in software or out of it (a talk, a business, a renovation)."
---

# Brainstorming

## First: What Do You Actually Know?

- Everything that matters is in the request. Do it, and say what you did.
- Something non-trivial is missing. Start the conversation.

Before implementing:

1. Lay out the approaches.
2. Write the design doc.
3. Get approval.
4. Invoke `writing-plans` skill.

Two things aren't implementing: a spike they said yes to, and doing what they asked once they've opted out of the questions.

## Look Before You Ask

In an existing project or with context, dig in before your first message. Read what they referred to and the code or material it connects to, and keep reading until you can explain how the relevant parts work today and what this change would touch. Never ask what the project or their context already answers.

## Your First Message

- They've already said what they want: aim for about 200 words. Echo their request back, add what you found, and end with one line inviting corrections, then one question about what they want.
- They haven't: one open question about the biggest thing their request leaves unsettled. Say why you're asking.

End with your question if they asked for brainstorming. Otherwise, add a light offer to just get going instead.

## The Conversation

Each message ends with one question. Use plain language, pitched just a little above where your human partner is. Match their vocabulary; never use process jargon.

Be clear and concise. Lead with what matters. Avoid jargon. When you report what you found, give them the most important findings and offer the rest.

**Get them describing.** Open questions come first. Offer a short menu only when they're stuck. When they say "just guess" or "what do you think?", propose something concrete.

**How it gets made.** Find out early which choices they want to make, which they're handing to you, and what they already have to work with. When there's existing work, build on what it already uses. Any choice you make goes in the design as your call.

**Ground to cover.** This is territory, not a script. Never read these out as questions:

- what kind of thing this is, and what makes it special
- why now, and what success looks like to them
- goals, non-goals, and anti-goals
- prior art: what they've seen elsewhere, loved or hated
- current state: what exists now, what they've tried
- the details they care about

**Make every question specific** to their project and what they've told you. Ask Socratically, the way a sharp colleague would.

**Offer recon.** Once you have a bit of grounding and looking further would help, offer to go look: deeper into their codebase or project, their own files and data, or the web. Say what you'd look for. They decide whether you go.

**Lay out the approaches.** Once you understand what they want, put the ways of building it in a message of its own. The design doc has an **Approaches** part: the two or three ways you considered building it, what each trades off, which one they picked, and why.

**Show mockups.** Offer it the first time one of the moments above comes up, never upfront. If they accept, read `visual-companion.md` in this directory before starting the server.

## Play It Back

Play back as you go. As soon as you understand one part well enough to describe it, describe that part back in about 200-300 words, then return to questions about the next part. Playback and questions alternate through the whole conversation; the last chunk covers whatever is left.

Only what they said goes in as theirs. Anything you filled in goes in as your proposal, with your reason. End each chunk by asking what's wrong or missing.

Before you send a chunk, check it: does it describe something they'll look at? If so, and they haven't seen the visual companion offer yet, send the offer instead and hold the chunk for the next message. Once they've accepted, put a mockup next to the description.

## Size the Work

Once you understand what they want and they've picked an approach, say how big the work is in plain words. They can override it.

| Size | The design doc |
|------|----------------|
| A small change | a short one: what you already covered together, written down |
| A project | the full written design |

Short or full, the design doc has an **Approaches** part.

If it grows mid-task, stop, say so, and step up a size.

If this is really several independent projects, say so, agree on an order, and brainstorm them one at a time.

## The Written Design

Write a plain document a talented builder in the domain could plan from without going back to your human partner. Cover:

- intent and the why
- goals, non-goals, anti-goals
- constraints
- approaches
- the parts of the how they decided, as they decided them
- what's left to the builder

For a small change, the short design covers the same points in a line or two each and goes straight to your human partner, without the builder check.

**Where it goes:** in a software repo, `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, committed. Otherwise, ask. Your human partner's preferences override both.

**Builder check** (for a project): dispatch a fresh subagent with `builder-check-prompt.md` in this directory. When you tell your human partner you're writing it up, say a reviewer will read it first and you may come back once with a few questions. Don't hand over the document until the check is back. Sort what the builder asks into three piles:

- **Answered already** by the conversation or the project: put the answer in the document.
- **Minor:** a sensible builder could settle it without changing what gets built. Settle it yourself and mark it in the document as your call.
- **Theirs:** only your human partner can answer it, and the answer changes what gets built.

Bring the "theirs" pile in one message, most important first. Update the document with their answers, then hand it over with a short list of the calls you made so they can check those while reading. That's the only round of questions the check produces. Without a subagent tool, read the document as that builder yourself.

<HARD-GATE>
Nothing gets built until your human partner approves the design doc: the short one for a small change, the full one for a project. Building includes writing product code, scaffolding, installing dependencies, creating projects, and invoking an implementation skill. Reading and exploring are fine.

Two exceptions. If they opted out of the questions, the skill is done and the gate goes with it. A spike they said yes to may be built; it stays labeled throwaway, and keeping what it produced is a new request that comes back through this gate.

After the design doc is approved, the next step is the plan: invoke `superpowers:writing-plans` and no other skill.
</HARD-GATE>

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll offer a menu of what they might want" | Options steer. Ask them to describe it first. |
| "I'll fill in sensible defaults" | Good. Say them out loud. A default they never heard is one they couldn't reject. |
| "I've answered their questions, so I'll write the doc" | Lay out the approaches first, in a message of their own. |
| "I should explain the process first" | Ask your question. The process shows itself. |
| "They said 'sounds good' to the idea" | Approval covers what you showed them. A design doc you haven't written isn't approved. |
| "The spike works, I'll keep building on it" | Keeping it is a new request. Back through the gate. |

## Visual Companion

A browser tab for showing mockups, diagrams, and prototypes. It's a tool, not a mode: accepting it doesn't send every question to the browser.

**Offer it just-in-time.** Offer it the first time one of the moments above comes up, never upfront. The offer is its own message with nothing else in it:

> "This might be easier if I show you. Want me to open a browser tab with some mockups?"

If they decline, stay in text and don't offer again unless they raise it.

**Per question, ask: would they understand this better by seeing it?**
Mockups, layouts, diagrams, and side-by-side designs go in the browser.
Requirements, scope, tradeoffs, and conceptual choices stay in text. A
question about a UI topic isn't automatically a visual question.

If they accept, read `visual-companion.md` in this directory before
starting the server.