"""One pass: assemble, rank, write the tables, render the browser, write the summary."""
import os
import pickle

import browser
import emit
import qcommon as Q
import summary_md


def main():
    Q.ensure_build()
    B = emit.build()
    hd, wd = emit.write(B)
    B["summaryStats"] = emit.summary(B)
    Q.dump_json(B["summaryStats"], os.path.join(Q.BUILD, "summary.json"))
    pickle.dump(B, open(os.path.join(Q.BUILD, "bundle.pkl"), "wb"))
    path, size = browser.render(B)
    md = summary_md.write(B)
    print(f"queue_hooks.tsv  {len(hd):>7,} hooks")
    print(f"queue_words.tsv  {len(wd):>7,} words")
    print(f"misswipes.tsv    {int((B['misswipes'].times >= 2).sum()):>7,} repeated strings")
    print(f"queue.html       {size / 1e6:>7.1f} MB")
    print(f"{md}")


if __name__ == "__main__":
    main()
