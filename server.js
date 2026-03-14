const express = require("express");
const { exec } = require("child_process");

const app = express();
app.use(express.json());
app.use(express.static("public")); // Serve HTML/JS

// API endpoint to execute command
app.post("/run", (req, res) => {
  const { command } = req.body;

  // ⚠️ Dangerous! Only use in safe/test environments
  if (!command) return res.status(400).json({ error: "No command provided" });

  // Optional: whitelist commands
  const allowed = ["ls", "pwd", "whoami", "date"];
  const cmdName = command.split(" ")[0];
  if (!allowed.includes(cmdName)) {
    return res.status(403).json({ error: "Command not allowed" });
  }

  exec(command, (err, stdout, stderr) => {
    if (err) return res.json({ error: stderr || err.message });
    res.json({ output: stdout });
  });
});

app.listen(3000, () => console.log("Server running on http://localhost:3000"));
