# Snippets

This folder contains sample snippets. Create your own snippets to speed up email composition.

## How to Create Snippets

1. Create a `.md` file in this folder or a subfolder
2. First line is the title (with or without `#`)
3. Rest of the file is the content that will be inserted

## Using Variables

You can use placeholders that will be replaced with your user settings:
- `[name]` - Your name
- `[company]` - Your company
- `[phone]` - Your phone number
- `[email]` - Your email

Configure these in `config.yaml` under `user.variables`.

## Organizing Snippets

Create subfolders to organize snippets by category:
```
snippets/
├── Greetings/
│   ├── formal.md
│   └── casual.md
├── Closings/
│   └── standard.md
└── Templates/
    └── meeting_request.md
```
