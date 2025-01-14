import argparse
import random
from fedml.core.security.defense.slsgd_defense import SLSGDDefense
from fedml.core.security.test.aggregation.aggregation_functions import (
    AggregationFunction,
)
from fedml.core.security.test.utils import create_fake_model_list


def add_args_option2():
    parser = argparse.ArgumentParser(description="FedML")
    parser.add_argument(
        "--yaml_config_file",
        "--cf",
        help="yaml configuration file",
        type=str,
        default="",
    )
    # default arguments
    parser.add_argument("--trim_param_b", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--option_type", type=int, default=2)
    args, unknown = parser.parse_known_args()
    return args


def add_args_option1():
    parser = argparse.ArgumentParser(description="FedML")
    parser.add_argument(
        "--yaml_config_file",
        "--cf",
        help="yaml configuration file",
        type=str,
        default="",
    )
    # default arguments
    parser.add_argument("--trim_param_b", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--option_type", type=int, default=1)
    args, unknown = parser.parse_known_args()
    return args


def test_defense_option2():
    defense = SLSGDDefense(add_args_option2())
    model_list = create_fake_model_list(20)
    random.shuffle(model_list)
    val = defense.run(
        model_list,
        base_aggregation_func=AggregationFunction.FedAVG,
        extra_auxiliary_info=model_list[0][1],
    )
    print(f"len={len(val)}, val={val}")


def test__sort_and_trim():
    defense = SLSGDDefense(add_args_option1())
    model_list = create_fake_model_list(20)
    random.shuffle(model_list)
    print(f"len(model_list) = {len(model_list)}")
    processed_model_list = defense._sort_and_trim(model_list)
    print(
        f"len(trimed_list) = {len(processed_model_list)}, processed model list = {processed_model_list}"
    )


def test_robustify_global_model():
    for alpha in [0, 0.5, 1]:
        model_list = create_fake_model_list(20)
        aggregated_results = SLSGDDefense(add_args_option2()).run(
            model_list,
            base_aggregation_func=AggregationFunction.FedAVG,
            extra_auxiliary_info=model_list[0][1],
        )
        print(f"alpha = {alpha}, aggregation = {aggregated_results} ")


if __name__ == "__main__":
    test_defense_option2()
    test__sort_and_trim()
    test_robustify_global_model()
