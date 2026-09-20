"""One pass: assemble, rank, write the tables, render the browser, write the summary."""
import os
import pickle

import browser
import emit
import hookrecord
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

    # The Phase 2 -> Phase 3 contract. Written here rather than by hand so the record and
    # the TSVs can never describe different queues.
    opp, opp_table, priors = hookrecord.opportunity()
    records = hookrecord.build(B, opp)
    _, full_size = hookrecord.write_full(records)
    _, bundle_size, bundled = hookrecord.write_bundle(records, opp_table=opp_table,
                                                      priors=priors)
    print(f"queue_hooks.tsv  {len(hd):>7,} hooks")
    print(f"queue_words.tsv  {len(wd):>7,} words")
    print(f"misswipes.tsv    {int((B['misswipes'].times >= 2).sum()):>7,} repeated strings")
    print(f"queue.html       {size / 1e6:>7.1f} MB")
    print(f"hooks.ndjson.gz  {full_size / 1e6:>7.1f} MB  ({len(records):,} hooks)")
    print(f"training_hooks   {bundle_size / 1e6:>7.1f} MB  ({bundled:,} hooks for the app)")
    print(f"{md}")


if __name__ == "__main__":
    main()
