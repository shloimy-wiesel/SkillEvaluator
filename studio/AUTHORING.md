# From a draft to an evaluation

Once your operator has [started Studio](README.md), all the steps below take place in your browser.

1. **Open your project.** Enter the repository’s HTTPS clone URL and the folder containing `SKILL.md`. Use `.` if the skill is at the root. On a self-managed GitLab instance, copy the URL from that instance’s **Code → Clone with HTTPS**, including any installation prefix, port, and nested groups. Reading needs repository read access; to save edits you also need permission to push to the branch (`write_repository` for a GitLab access token).
2. **Create a version.** Open **Edit skill**, choose a source branch and create your own branch. Preview your changes, then save. Saving publishes a Git commit. If a collaborator has pushed since you opened the editor, review the newer branch before reapplying your draft.
3. **Prepare your dataset.** Start with one case: enter a task and the outcome you expect. Add assertions or fixtures when the task needs them. Preview and validate your changes before **Commit and push**. A generated preview does not replace the saved dataset until you commit it.
4. **Choose your evaluation.** For a quick keyless check, open **Evaluation runs** and select schema or Unicode checks. Use the advanced checks for a broader assessment. For Tier 2, save both chat and embedding settings and choose the overlap checks. For Tier 3, prepare the dataset, configure chat, and choose the agent and trial settings. Live evaluation needs an operator-enabled [live worker](README.md#live-tier-3-image).
5. **Read the result.** Before starting, check the selected commit. You can close the browser after queuing. Reopen run history to inspect findings or download the available reports. A failed gate still has useful evidence. An interrupted run is labeled as such: rerun explicitly if needed.
6. **Compare versions.** Open **Results → Compare revisions**, select the earlier and newer revisions, then pick the run you want on each side. A change in files does not necessarily mean a change in skill performance. Studio explains when missing results or different evaluation settings prevent a meaningful score comparison.

**Using your company’s GitLab?** See [self-managed GitLab setup](GITLAB.md) for the installation URL, private CA, and separate Git and API credentials. Repository access is enough to author a skill. Connect the project API when you also want to create merge requests or inspect pipelines and jobs from Studio.

**Branch versus commit:** the branch is where you continue writing. The commit recorded on a run identifies what was evaluated even after another save moves the branch.
