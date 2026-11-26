# Third-party notices

Code in Roundtable Hold that was taken or ported from other projects, with each
project's licence. Roundtable Hold itself is MIT.

## dsh-plugin-save-token 2.1.3

- Source: the DeepSeek Harness plugin `dsh-plugin-save-token` (npm package, also
  github.com/vibe-any/dsh-plugin-save-token), file `src/index.js`.
- Ported to Python in `src/roundtable/harness/saver.py`: the token estimate (`estTokens`),
  the TOON-style re-encoding of uniform JSON arrays (`uniformKeys`, `toonEncode`,
  `findDominantUniformArray`), the structural JSON shortening (`transformValue`), the
  line compressor and its table mode (`collapseBlanks`, `collapseRepeats`,
  `trimLongLines`, `delimiterProfile`, `looksTabular`, `windowLines`,
  `windowLinesStrided`, the error-line pattern), the never-worse gate
  (`buildCandidate`), spill-before-replace, the cross-turn dedupe and the expand tool
  (`save_token_expand`, here `expand_output`), with the plugin's default settings
  (`cordis.patch.yml`). Its dashboard and its compaction trigger were not taken.

```
MIT License

Copyright (c) 2026 PlayWithAI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
