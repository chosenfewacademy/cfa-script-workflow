# Natural Dialogue: how real people talk, and how CFA scripts should sound

This doc studies three things: conversation analysis (how talk actually works), screen-dialogue craft (how writers make that readable), and real unscripted speech (the Resilia-style transcripts in this folder plus corpus findings). Everything here is folded into the tool's script rules (DIALOGUE_RULES → "SOUNDS LIKE REAL PEOPLE"), the critic (SYS_ACCURACY kind `stiff`, read-aloud `human` score), the voice lint, and the director (listener reactions and gestures).

## 1. What conversation analysis tells us
| Finding | Evidence | What we do with it |
|---|---|---|
| Turns follow each other very fast. The typical gap is about 200 ms, under 5% of speech overlaps, and most overlaps last less than 100 ms. | Levinson & Torreira 2016, cited in *Timing in Conversation* (J. Cognition); Stivers et al. 2009 found median gaps of 0–300 ms across 10 languages | Keep lines short and punchy and avoid long setups. The renderer's gap between lines (0.6–0.7 s) leaves room to react. |
| A long gap carries meaning: reluctance, bad news, a dispreferred answer. | Kendrick & Torreira 2015; Bögels et al. 2015 (same review) | Use `[short pause]` before a hard truth, never everywhere. |
| Repair ("wait, what?", "the— no, the other one") is normal and comes after longer gaps (mode about 700 ms). | Kendrick 2015, *Frontiers in Psychology* (PMC4357221) | Characters self-correct and ask "Wait, what?" when they are confused. |
| "uh" signals a short delay and "um" a long one. Speakers use them deliberately to hold or give up the floor. | Clark & Fox Tree 2002, *Cognition* | Light filler only ("wait", "hold on", "okay so"). Use "um" at most once per episode, because TTS overplays it. |
| Faster replies feel more connected and more enjoyable. | Templeton et al. 2022 (same review) | Reactions land immediately ("Huh." / "No way.") before the real reply. |

## 2. Screen-dialogue craft
Real speech transcribed word for word is unreadable. Screen dialogue is a *heightened simulation* of it (EnsembleWriter). Each line should advance the plot, reveal character, or create conflict.
- **Subtext, not "on the nose."** People rarely say exactly what they feel. Fear comes out as a joke and pride as a shrug (Final Draft, Script Anatomy, StorySense).
- **Conflicting agendas.** Two people who want different things talk past each other, and the scene feels alive (Final Draft).
- **Interruptions and overlap** show urgency, power, or not listening. Mark them with an em dash, and use them only where they matter (Leyline, StorySense).
- **Distinct voices.** Each character has their own vocabulary, rhythm and slang. One rambles and another gives one-word answers (Script Anatomy).
- **Read it aloud.** This is the single most useful test, and it is what our read-aloud critic does.

## 3. What we saw in real unscripted speech (Resilia-style and street-interview transcripts in this folder)
- People react before they answer: "Wait—", "Hold on.", "Huh.", "Okay, so…".
- They start, stop and restart: "I thought it was— no, it was the other app."
- They answer a question with a question: "You sent it where?"
- They call back to something said earlier: "Like the coffee thing."
- Line length is very uneven: a one-word reaction can sit next to a three-sentence thought.
- Nobody explains things the listener already knows.

## 4. Rules now in the tool (DIALOGUE_RULES)
**Do:**
- react before replying;
- interrupt (end the cut-off line with —);
- use half-finished and self-corrected lines;
- answer a question with a question;
- carry subtext;
- use callbacks;
- give each character slang that fits them (Jordan casual, Dee blunt, Okafor proverbs);
- keep line lengths uneven;
- use v4 performance tags `[sighs] [laughs] [chuckles] [exhales] [short pause]`, at most one per 5 lines and on character lines only.

**Never:**
- "As you know…" exposition;
- a monologue longer than 3 sentences;
- tidy question → answer → thanks turn-taking;
- characters speaking in complete, grammatical paragraphs.

**Critic:** SYS_ACCURACY now has the kind `stiff` (a line no real person would say aloud). It is fixed in the targeted revise. The read-aloud `human` score is redefined as "sounds like real people talking." The A/B judge adds `human_likeness`.

**Visuals:** the director alternates speaker close-ups with LISTENER REACTION shots on punchlines, surprises and the reveal. Each character line gets a `gesture`, which is passed to the lip-sync prompt ("While speaking: …").

**Audio tags:** the tags are stripped from word counts, captions, beat timing and render alignment (AUDIO_TAG_RE / strip_tag_words), so they are only ever performed, never shown.

## Sources
- Journal of Cognition, "Timing in Conversation": https://journalofcognition.org/articles/10.5334/joc.268
- Kendrick 2015, timing of other-initiated repair: https://pmc.ncbi.nlm.nih.gov/articles/PMC4357221/
- Clark & Fox Tree 2002, "Using uh and um in spontaneous speaking": http://www.columbia.edu/~rmk7/HC/HC_Readings/Clark_Fox.pdf
- Heldner & Edlund 2010 / "Overrated gaps" (MPI): https://pure.mpg.de/rest/items/item_3362863_2/component/file_3365365/content
- Script Anatomy, How to write great dialogue: https://scriptanatomy.com/how-to-write-great-dialogue/
- Final Draft, How to write subtext in dialogue: https://www.finaldraft.com/blog/how-to-write-subtext-in-dialogue
- StorySense, Dialogue: https://www.storysense.com/format/dialogue.htm
- EnsembleWriter, Dialogue and parentheticals: https://ensemblewriter.com/docs/dialogue-and-parentheticals
- Leyline, Dialogue writing for screenplays: https://leylinepro.net/dialogue-writing-for-screenplays/
