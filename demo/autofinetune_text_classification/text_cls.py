from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import ast
import shutil

import paddlehub as hub
import os
from paddlehub.common.logger import logger

parser = argparse.ArgumentParser(__doc__)
parser.add_argument("--epochs", type=int, default=3, help="epochs.")

# the name of hyper-parameters to be searched should keep with hparam.py
parser.add_argument("--batch_size", type=int, default=32, help="batch_size.")
parser.add_argument(
    "--learning_rate", type=float, default=5e-5, help="learning_rate.")
parser.add_argument(
    "--warmup_prop", type=float, default=0.1, help="warmup_prop.")
parser.add_argument(
    "--weight_decay", type=float, default=0.01, help="weight_decay.")

parser.add_argument(
    "--max_seq_len",
    type=int,
    default=128,
    help="Number of words of the longest seqence.")
parser.add_argument(
    "--checkpoint_dir",
    type=str,
    default=None,
    help="Directory to model checkpoint")

# saved_params_dir and model_path are needed by auto fine-tune
parser.add_argument(
    "--saved_params_dir",
    type=str,
    default="",
    help="Directory for saving model during ")
parser.add_argument(
    "--model_path", type=str, default="", help="load model path")
args = parser.parse_args()


def is_path_valid(path):
    if path == "":
        return False
    path = os.path.abspath(path)
    dirname = os.path.dirname(path)
    if not os.path.exists(dirname):
        os.mkdir(dirname)
    return True


if __name__ == '__main__':
    # Load Paddlehub ERNIE pretrained model
    module = hub.Module(name="ernie")
    inputs, outputs, program = module.context(
        trainable=True, max_seq_len=args.max_seq_len)

    # Download dataset and use ClassifyReader to read dataset
    dataset = hub.dataset.ChnSentiCorp()
    metrics_choices = ["acc"]

    reader = hub.reader.ClassifyReader(
        dataset=dataset,
        vocab_path=module.get_vocab_path(),
        max_seq_len=args.max_seq_len)

    # Construct transfer learning network
    # Use "pooled_output" for classification tasks on an entire sentence.
    pooled_output = outputs["pooled_output"]

    # Setup feed list for data feeder
    # Must feed all the tensor of ERNIE's module need
    feed_list = [
        inputs["input_ids"].name,
        inputs["position_ids"].name,
        inputs["segment_ids"].name,
        inputs["input_mask"].name,
    ]

    # Select fine-tune strategy, setup config and fine-tune
    strategy = hub.AdamWeightDecayStrategy(
        warmup_proportion=args.warmup_prop,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        lr_scheduler="linear_decay")

    # Setup RunConfig for PaddleHub Fine-tune API
    config = hub.RunConfig(
        checkpoint_dir=args.checkpoint_dir,
        use_cuda=True,
        num_epoch=args.epochs,
        batch_size=args.batch_size,
        enable_memory_optim=True,
        strategy=strategy)

    # Define a classfication fine-tune task by PaddleHub's API
    cls_task = hub.TextClassifierTask(
        data_reader=reader,
        feature=pooled_output,
        feed_list=feed_list,
        num_classes=dataset.num_labels,
        config=config,
        metrics_choices=metrics_choices)

    # Load model from the defined model path or not
    if args.model_path != "":
        with cls_task.phase_guard(phase="train"):
            cls_task.init_if_necessary()
            cls_task.load_parameters(args.model_path)
            logger.info("PaddleHub has loaded model from %s" % args.model_path)

    cls_task.finetune()
    run_states = cls_task.eval()
    eval_avg_score, eval_avg_loss, eval_run_speed = cls_task._calculate_metrics(
        run_states)

    # Move ckpt/best_model to the defined saved parameters directory
    best_model_dir = os.path.join(config.checkpoint_dir, "best_model")
    if is_path_valid(args.saved_params_dir) and os.path.exists(best_model_dir):
        shutil.copytree(best_model_dir, args.saved_params_dir)
        shutil.rmtree(config.checkpoint_dir)

    # acc on dev will be used by auto fine-tune
    hub.report_final_result(eval_avg_score["acc"])
