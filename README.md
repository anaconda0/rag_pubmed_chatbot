# PubMed RAG Chatbot

A beginner-friendly Retrieval-Augmented Generation (RAG) chatbot for the Kaggle
PubMed Multilabel Text Classification dataset.

The project reads PubMed abstracts from a CSV file, chunks the abstracts,
generates sentence-transformers embeddings, stores the chunks in MongoDB, and
uses semantic retrieval to answer questions through a Gradio chat interface.

## Features

- Detects the PubMed CSV file from the `data/` folder.
- Prints dataset columns and the first 3 rows before ingestion.
- Automatically detects the abstract/text column.
- Cleans and chunks PubMed abstracts.
- Generates embeddings with `sentence-transformers`.
- Stores chunks, embeddings, labels, PMID, title, and source metadata in MongoDB.
- Avoids duplicate chunks with a SHA-256 hash.
- Retrieves the top 5 most similar chunks using cosine similarity.
- Includes chatbot memory:
  - short-term memory: last 20 messages in the current session
  - long-term memory: past user/assistant messages stored in MongoDB
- Provides a Gradio UI with:
  - chat interface
  - streaming response
  - session management
  - prompt history panel
  - clear button
  - retrieved source/chunk display

## Project Structure

```text
rag_pubmed_chatbot/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── data/
│   └── .gitkeep
├── src/
│   ├── chunking.py
│   ├── config.py
│   ├── database.py
│   ├── embeddings.py
│   ├── ingest.py
│   ├── memory_manager.py
│   ├── rag_chain.py
│   └── retriever.py
└── ui/
    └── gradio_ui.py
```

## Important Dataset Note

The Kaggle CSV files are not committed to GitHub.

Place the downloaded dataset CSV file inside:

```text
data/
```

This repository ignores `data/*.csv` because the processed CSV is larger than
GitHub's 100 MB single-file limit.

## Requirements

- Python 3.11 recommended
- MongoDB running locally or a MongoDB Atlas URI
- Kaggle PubMed Multilabel Text Classification CSV file

## Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file from the example:

```powershell
copy .env.example .env
```

Default MongoDB settings:

```text
MONGO_URI=mongodb://localhost:27017
MONGO_DATABASE_NAME=rag_pubmed_chatbot
MONGO_COLLECTION_NAME=pubmed_chunks
MONGO_MEMORY_COLLECTION_NAME=chat_memory
```

## Ingest the Dataset

First, inspect the CSV without writing to MongoDB:

```powershell
python src/ingest.py --inspect-only
```

Test ingestion on a few rows:

```powershell
python src/ingest.py --limit 100
```

Run full ingestion:

```powershell
python src/ingest.py
```

The ingestion script will:

- read a CSV from `data/`
- print file name, columns, and first 3 rows
- detect the text/abstract column
- clean and chunk abstracts
- generate embeddings
- store chunks and metadata in MongoDB
- skip duplicate chunks

## Run Retrieval from the Command Line

```powershell
python src/retriever.py "What does the dataset say about HPV and cervical cancer?"
```

## Run the RAG Pipeline from the Command Line

```powershell
python src/rag_chain.py "What does the dataset say about HPV and cervical cancer?"
```

This prints:

- retrieved dataset chunks
- short-term memory
- relevant long-term memory
- final prompt
- final answer

## Run the Gradio Chatbot

```powershell
python app.py
```

Then open:

```text
http://127.0.0.1:7860
```

## How the RAG Flow Works

1. The user asks a question in the Gradio UI.
2. The question is embedded with the same sentence-transformers model used for ingestion.
3. MongoDB chunk embeddings are scanned and ranked with cosine similarity.
4. The top 5 PubMed chunks are added to the prompt.
5. The last 20 session messages are added as short-term memory.
6. Relevant older MongoDB memory messages are retrieved and added.
7. The app generates a context-grounded answer from retrieved PubMed chunks.
8. The user question and assistant answer are saved to memory.

## Current Answer Generation

The current answer generator is local and extractive. It selects relevant
sentences from retrieved PubMed abstracts instead of calling an external LLM.

This keeps the project runnable without API keys. A hosted or local LLM can be
added later by sending the final prompt from `src/rag_chain.py` to the model.

## Main Files

- `src/config.py`: environment variables and project settings
- `src/database.py`: MongoDB helpers and indexes
- `src/embeddings.py`: sentence-transformers wrapper
- `src/chunking.py`: text cleaning and chunk splitting
- `src/ingest.py`: CSV inspection and MongoDB ingestion
- `src/retriever.py`: cosine similarity retrieval
- `src/memory_manager.py`: short-term and long-term chatbot memory
- `src/rag_chain.py`: RAG prompt building and answer generation
- `ui/gradio_ui.py`: Gradio interface
- `app.py`: launches the Gradio app

## GitHub Notes

Do not commit:

- `.env`
- `venv/`
- `logs/`
- `data/*.csv`

The dataset must be downloaded separately from Kaggle and placed in `data/`.
