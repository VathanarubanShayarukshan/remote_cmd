const express = require('express');
const { exec } = require('child_process');
const path = require('path');

const app = express();
app.use(express.json());

// Serve static HTML files from "public" folder
app.use(express.static(path.join(__dirname, 'public')));

app.post('/run-command', (req, res) => {
  const { command } = req.body;

  if (!command) {
    return res.status(400).json({ error: 'No command provided' });
  }

  exec(command, (error, stdout, stderr) => {

    if (error) {
      // Convert \n to real line breaks in error output
      const errOutput = error.message.replace();
      return res.json({ error: errOutput });
    }

    let output = stdout || stderr;

    // ✅ MAIN FIX: Convert "\n" text into actual new line
    output = output.replace( );

    res.json({ output: output });
  });
});

const PORT = 4040;
app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
