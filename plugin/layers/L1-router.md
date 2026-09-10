# The router - which capability fires, and when it must not

A skill listing tells you what each skill IS. That is the wrong key. You need to know which
situation you are in, because that is what you can actually observe about the turn you are handling.
Match the row, then fire. If no row matches, fire nothing - an unfired skill costs nothing and a
wrongly fired one costs a body load plus a detour.

| The situation you are actually in | Fire | Do NOT fire it when |
|---|---|---|
| A new capability was asked for and its shape is not settled | `brainstorming` | the shape is already written in the state file or the plan - then you are executing, not shaping |
| The work spans more than one session, or more than about four files | `writing-plans` | it is one edit you can finish and verify in this turn |
| A written plan exists and you are working it | `executing-plans` | there is no plan file - write one first or do the single slice |
| Something behaves wrong and you do not yet know why | `systematic-debugging` | you have already located the cause and are applying it |
| A change is finished and about to be accepted | `requesting-code-review` | nothing changed, or the change is a copy edit |
| Review feedback landed and some of it looks wrong | `receiving-code-review` | you agree with all of it - just apply it |
| You are about to say done, fixed, working, or ready | `verification-before-completion` | never skip this one; it is the last gate before a false claim |
| Several pieces are independent and none blocks another | `dispatching-parallel-agents` | they share files or state, or one needs the other's output |
| You need a symbol, a caller, or the blast radius of an edit | the project's index (graph, code-map, code-index) | it is prose, config, or copy - grep is correct for text |
| The design of a surface is being decided | the project's design skill, with real references | you have no reference material - go get some rather than inventing a layout |

**Three rules that outrank the table.**

Skills are pulled, hooks are pushed. A rule you must not violate belongs in a hook, where it is
enforced. A rule about how to do good work belongs in a skill, where it is advice you choose to
take. If you find yourself hoping a skill will stop you doing something, it will not.

One at a time. Firing three skills at the start of a turn loads three bodies and gets you three
sets of instructions competing for the same decision. Fire one, act, then re-read the situation.

A skill that is not in the table is still available, but its own description has to earn the load:
read the description, and if it does not name a situation that matches this turn, do not open it.
