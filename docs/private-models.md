# Getting started with a private model (v2ecoli)

compose-api runs simulations for you on UConn Health's computing cluster: you send it a model, it runs it there, and
you download the results. Some models on it are private. v2ecoli, Eran Agmon's lab's whole-cell model of *E. coli*, is
one of them: only people who have been given access can see it or run it.

You run v2ecoli from the **workbench**, a web page that runs on your own computer. It shows v2ecoli's models and sends
the runs to compose-api for you. This page takes you from nothing to a finished run.

## What you need

- **The Google account whose email you gave us.** Access is tied to that email address, so sign in with that account
  every time.
- **A GitHub account** that has been given access to v2ecoli's code (it is private too).
- **macOS or Linux.** On Windows, use a lab Mac or Linux machine.
- **A terminal:** Terminal on macOS, any terminal on Linux. You type every command below there.

## 1. Check your access on the web

1. Open <https://compose.cam.uchc.edu/ui>.
2. Click **Sign in** (top right) and choose **Google**. Use the Google account whose email you gave us. The first time,
   this also creates your compose-api account.
3. Open the account menu (top right, where **Sign in** was). It shows the email you're signed in with and, under it,
   your roles. `repo-v2ecoli` should be one of them, for example:

   ```text
   Roles: repo-v2ecoli, user
   ```

   `repo-v2ecoli` is your access to v2ecoli; `user` is what every account has.

**Don't see `repo-v2ecoli`?**

- Check the email in the menu. If it isn't the one you gave us, choose **Sign out** and sign in again with the right
  Google account.
- If you signed in to compose-api before your access was set up, sign out and back in: your roles are read when you sign
  in.
- Still missing? Ask Alex Patrie on Slack, and tell him the email the menu shows. (Slack, not a GitHub issue: anyone
  can read an issue.)

## 2. Install (once)

### uv

uv installs Python tools, and fetches a suitable version of Python for you:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close the terminal and open a new one.

### A C compiler

v2ecoli compiles parts of itself when it installs. On macOS, run:

```bash
xcode-select --install
```

If it says the tools are already installed, you're set. On Linux (Ubuntu), run `sudo apt install build-essential`.

### Sign in to compose-api

The workbench sends your runs to compose-api as you, so you sign in once from the terminal. Install the sign-in tool:

```bash
uv tool install "compose-api-client[cli]"
```

Then sign in:

```bash
compose-api auth login --provider google
```

Your browser opens Google's sign-in. Choose the same Google account as in step 1, then come back to the terminal. It
prints a few lines, among them:

```text
Session: valid, until ...
API: confirmed this identity just now
```

That means you're signed in. If a line says `Capabilities: none beyond a signed-in user`, that's normal: your v2ecoli
access is the role you saw in step 1.

If the terminal says `compose-api: command not found`, run `uv tool update-shell`, open a new terminal, and try again.

The tool keeps your sign-in in your computer's password store (Keychain on macOS), so you won't need to do this again
for a while. If the workbench later says you aren't signed in, run `compose-api auth login --provider google` again.

### v2ecoli and the workbench

v2ecoli's code is on GitHub. Install the GitHub CLI from <https://cli.github.com>, then sign in to GitHub once:

```bash
gh auth login
```

Choose **GitHub.com**, then **HTTPS**, and sign in with your GitHub account in the browser. Then download v2ecoli and
install it with the workbench:

```bash
gh repo clone vivarium-collective/v2ecoli
cd v2ecoli
uv sync --extra report
```

The last line installs v2ecoli, the workbench and everything they need. The first time, it takes several minutes.

## 3. Start the workbench

In the `v2ecoli` folder:

```bash
uv run vivarium-workbench serve --backend-base-url https://compose.cam.uchc.edu
```

It prints a few lines, ending with `Uvicorn running on http://127.0.0.1:<port>`. Open that address in your browser.
Leave the terminal open: closing it stops the workbench. To stop it yourself, press Ctrl+C there.

Next time, open a terminal, `cd v2ecoli`, and run the same `uv run vivarium-workbench serve ...` line.

## 4. Run the single cell

1. In the left column, click **Process**.
2. In the **Registry** panel, type `single` in the search box, then click **ecoli_single_cell**: one cell growing. Its
   card says **Runs: Cloud**: the workbench sends its runs to compose-api.
3. Below the picture of the model, set **Duration** to `60` (seconds of the cell's life), then click **▶ Run**.
4. After a minute or two it shows **✓ complete**. Under **Outputs**, **Results** lists what the run recorded (61 rows,
   one per simulated second), and **⬇ Download results** saves them.

Your runs are private: only you can see them.

For now, ecoli_single_cell is the only v2ecoli model compose-api runs. The others also say **Runs: Cloud**, but pressing
**▶ Run** on them shows **Run failed — no results produced**. That's expected until compose-api can run them, which is
coming. Use ecoli_single_cell.

### Limits

- Up to 1,000 s works for everyone. Longer runs need the `long-runs` role (ask Alex); without it, compose-api refuses the
  run before it starts.
- Keep runs to 2,400 s or less for now: the cell divides at about 2,500 s, and a run that reaches the division
  currently ends with no results.

If a run fails or is refused, note the message the workbench shows and tell Alex (see [Help](#help)).

## Help

- Questions, or something didn't work: ask Alex Patrie on Slack, or open an issue at
  <https://github.com/biosimulations/compose-api/issues> (anyone can read it, so leave out your email and anything
  private).
