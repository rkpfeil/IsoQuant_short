############################################################################
# Copyright (c) 2020 Saint Petersburg State University
# # All Rights Reserved
# See file LICENSE for details.
############################################################################

# takes teamcity config as input and check isoquant results

import os
import sys
from traceback import print_exc
import subprocess


_quote = {"'": "|'", "|": "||", "\n": "|n", "\r": "|r", '[': '|[', ']': '|]'}


def escape_value(value):
    return "".join(_quote.get(x, x) for x in value)


class TeamCityLog:

    text = ""

    def _tc_out(self, token, **attributes):
        message = "##teamcity[%s" % token

        for k in sorted(attributes.keys()):
            value = attributes[k]
            if value is None:
                continue

            message += (" %s='%s'" % (k, escape_value(value)))

        message += "]\n"
        sys.stdout.write(message)
        sys.stdout.flush()

    def start_block(self, name, desc):
        sys.stdout.flush()
        self._tc_out("blockOpened", name = name, description = desc)

    def end_block(self, name):
        sys.stdout.flush()
        self._tc_out("blockClosed", name = name)

    def log(self, s):
        self.text += s + "\n"
        self._tc_out("message", text = s)

    def warn(self, s):
        msg = "WARNING: " + s + "\n"
        self.text += msg
        self._tc_out("message", text = s, status = 'WARNING')

    def err(self, s, context = ""):
        msg = "ERROR: " + s + "\n"
        self.text += msg
        self._tc_out("message", text = s, status = 'ERROR', errorDetails = context)

    def print_log(self):
        print(self.text)

    def get_log(self):
        return self.text

    def record_metric(self, name, value):
        self._tc_out("buildStatisticValue", key=name, value=value)


def load_tsv_config(config_file):
    config_dict = {}
    for l in open(config_file):
        if l.startswith("#"):
            continue

        tokens = l.strip().split('\t')
        if len(tokens) < 2:
            continue

        config_dict[tokens[0]] = tokens[1]
    return config_dict


def fix_path(config_file, path):
    if path.startswith('/'):
        return path

    return os.path.join(os.path.dirname(config_file), path)


def main(args):
    log = TeamCityLog()

    if len(args) < 1:
        log.err("Provide configuration file")
        exit(-2)

    config_file = args[0]
    if not os.path.exists(config_file):
        log.err("Provide correct path to configuration file")
        exit(-3)

    source_dir = os.path.dirname(os.path.realpath(__file__))
    isoquant_dir = os.path.join(source_dir, "../../")

    log.log("Loading config from %s" % config_file)
    config_dict = load_tsv_config(config_file)
    assert "genedb" in config_dict
    assert "reads" in config_dict
    assert "datatype" in config_dict
    assert "output" in config_dict
    assert "name" in config_dict

    label = config_dict["name"]
    output_folder = os.path.join(config_dict["output"], label)
    genedb = fix_path(config_file, config_dict["genedb"])
    reads = fix_path(config_file, config_dict["reads"])

    log.start_block('isoquant', 'Running IsoQuant')
    isoquant_command_list = ["python", os.path.join(isoquant_dir, "isoquant.py"), "-o", output_folder,
                    "--genedb", genedb, "-d", config_dict["datatype"], "-t", "16", "-l", label]
    if "bam" in config_dict:
        isoquant_command_list.append("--bam")
        bam = fix_path(config_file, config_dict["bam"])
        isoquant_command_list.append(bam)
    else:
        assert "genome" in config_dict
        isoquant_command_list.append("--fastq")
        isoquant_command_list.append(reads)
        isoquant_command_list.append("--r")
        isoquant_command_list.append(fix_path(config_file, config_dict["genome"]))
        bam = os.path.join(output_folder, "%s/%s.bam" % (label, label))

    if "isoquant_options" in config_dict:
        isoquant_command_list.append(config_dict["isoquant_options"].replace('"', ''))

    log.log("IsoQuant command line: " + " ".join(isoquant_command_list))
    result = subprocess.run(isoquant_command_list)
    assert result.returncode == 0
    output_tsv = os.path.join(output_folder, "%s/%s.read_assignments.tsv" % (label, label))
    log.end_block('isoquant')

    log.start_block('quality', 'Running quality assessment')
    quality_report = os.path.join(output_folder, "report.tsv")
    qa_command_list = ["python", os.path.join(isoquant_dir, "src/assess_assignment_quality.py"),
                       "-o", quality_report, "--gene_db", genedb, "--tsv", output_tsv,
                       "--mapping", bam, "--fasta", reads]

    log.log("QA command line: " + " ".join(qa_command_list))
    result = subprocess.run(qa_command_list)
    assert result.returncode == 0
    log.end_block('quality')

    if "etalon" not in config_dict:
        return 0

    log.start_block('assessment', 'Checking quality metrics')
    etalon_qaulity_dict = load_tsv_config(fix_path(config_file, config_dict["etalon"]))
    quality_report_dict = load_tsv_config(quality_report)
    for k, v in etalon_qaulity_dict.items():
        assert k in quality_report_dict
        lower_bound = float(v) * 0.99
        upper_bound = float(v) * 1.01
        assert lower_bound <= float(quality_report_dict[k]) <= upper_bound

    log.end_block('assessment')


if __name__ == "__main__":
    # stuff only to run when not called via 'import' here
    try:
        main(sys.argv[1:])
    except SystemExit:
        raise
    except:
        print_exc()
        sys.exit(-1)
