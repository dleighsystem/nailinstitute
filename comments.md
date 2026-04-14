Ok, here's what I would do if it were my work, in order:

1) fix the documentation and metadata drift immediately - run multi-vendor model "audits" on the repo, code ground truth vs documentation, flagging the high variance findings as potential code bugs to review, and leaning toward code as truth, documentation as drift suspects. Different model vendors have different priors and blind spots, use multiple to get good coverage. Review the high variance findings, batch the rest, get the code and docs 1:1, fix the obvious bugs, add the remainder to a DEBT.md tracker and attack them later.

2) Identify the highest leverage CI/CD and pre-commit hooks (custom scripts even, but don't go down the rabbit hole) to lock in your new 1:1 alignment and enforce it moving forward. Add a docs sweep to your workflow to ensure they never outpace each other as you continue to build.

3) Find the seams - this has the potential to be three separate projects. I see three core patterns:

- AVE cards, validator, registry, etc
- Catalog of microservices
- Programatic / publication ecosystem

These have enough waist to justify giving them their own belt and suspenders treatment. Start explicitly writing their inner-module API contracts and plan to extract them into their own repos. Monolithic prototype --> 3 polished production repos.

This reduces the cognitive burden for others, and helps establish composability moving forward. If you have to use your own public API, it will be polished when others attempt to use it.