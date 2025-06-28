import argparse
import os
import pandas as pd
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
import torch

def train(args):
    """
    Main training function.  Handles training of the model on the given path.
    """
    # --- 1. Load Data ---
    print("Loading processed data...")
    # The training data is mounted by SageMaker in the path specified by the 'training' channel.
    input_data_path = os.path.join(args.training_dir, 'sentiment-train-data-sampled.parquet')
    df = pd.read_parquet(input_data_path)

    # Need to do this as the tokenizer will look to use the label column as the target values.
    df.rename(columns={'sentiment': 'label'}, inplace=True)

    
    # Convert pandas DataFrame to Hugging Face Dataset
    dataset = Dataset.from_pandas(df)
    
    # --- 2. Preprocess and Tokenize Data ---
    print("Tokenizing data...")
    # Load the tokenizer for the pre-trained model
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    def tokenize_function(examples):
        # The tokenizer will pad and truncate the text to a standard length
        return tokenizer(examples['review_full_text'], padding="max_length", truncation=True)

    # Apply the tokenizer to the entire dataset
    tokenized_datasets = dataset.map(tokenize_function, batched=True)
    
    # Split the dataset into training and testing sets
    train_test_split = tokenized_datasets.train_test_split(test_size=0.1)
    train_dataset = train_test_split['train']
    eval_dataset = train_test_split['test']

    # --- 3. Load Pre-trained Model ---
    print("Loading pre-trained model...")
    # We load the model and specify it's for sequence classification with 2 labels (0: neg, 1: pos)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_name, num_labels=2)
    
    # Check if a GPU is available and move the model to the GPU
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"Using device: {device}")


    # --- 4. Set up Trainer ---
    print("Setting up training arguments...")
    # These arguments define the training process, such as learning rate, batch size, etc.
    training_args = TrainingArguments(
        output_dir=args.model_dir,          # Output directory for the trained model
        num_train_epochs=args.epochs,       # Number of times to iterate over the training data
        per_device_train_batch_size=args.train_batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        warmup_steps=args.warmup_steps,
        weight_decay=0.01,
        logging_dir=f"{args.output_data_dir}/logs",
        evaluation_strategy="epoch",        # Evaluate performance at the end of each epoch
        save_total_limit=1,
    )

    # The Trainer class from Hugging Face handles the entire training loop
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
    )

    # --- 5. Train Model ---
    print("Starting model training...")
    trainer.train()
    print("Training complete.")


    # --- 6. Save Model ---
    # The trained model is saved to the directory specified by SageMaker (`SM_MODEL_DIR`)
    print(f"Saving model to {args.model_dir}")
    trainer.save_model(args.model_dir)
    tokenizer.save_pretrained(args.model_dir)


if __name__ == "__main__":
    # This block gets executed when the script is run.
    # It parses command-line arguments passed by the SageMaker Training Job.
    parser = argparse.ArgumentParser()

    # Hyperparameters sent by the client
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--train-batch-size", type=int, default=16)
    parser.add_argument("--eval-batch-size", type=int, default=8)
    parser.add_argument("--warmup-steps", type=int, default=500)
    parser.add_argument("--model-name", type=str, default="distilbert-base-uncased")

    # SageMaker environment variables
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR"))
    parser.add_argument("--training-dir", type=str, default=os.environ.get("SM_CHANNEL_TRAINING"))
    parser.add_argument("--output-data-dir", type=str, default=os.environ.get("SM_OUTPUT_DATA_DIR"))
    
    args, _ = parser.parse_known_args()
    
    train(args)