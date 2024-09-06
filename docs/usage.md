
# Usage

SeReTo provides a *command line interface (CLI)* to help you create and manage your reports. After you have [set it up](getting_started/installation.md), you can continue with the following steps.

## Getting Help

Any time you are unsure about anything, or cannot remember a command structure, you can always check the command's help:

```sh
sereto --help
```

You can also use help in the nested commands. For example, if you would like to know, what you can do with the dates in your report's configuration, you can run:

```sh
sereto config dates --help
```

## Create Report

To create a new report using SeReTo, you can use the `new` command. The command takes a unique identifier for the report as a positional argument. For example, to create a report with the identifier `TEST`, you would run the following command:

```sh
sereto new TEST
```

During the creation process, you will be prompted with questions about the report, such as its name. Please provide the necessary information when prompted.

Please note that the report identifier should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.

For more information on the `new` command, you can refer to the [SeReTo CLI documentation](reference/cli/cli.md#sereto.cli.cli.new).

![](assets/sereto-new.gif)


## List Reports

You can see the list of all reports (including our newly created one) using the following command, which will show you the ID and name of the report, as well as the location of the report's file structure:

```sh
sereto ls
```

![](assets/sereto-ls.gif)


## Configuring The Report's Details

SeReTo will need some information from you to generate the report. In our example, please change your working directory to your report's directory (you can discover it by running `sereto ls`, remember?). It can look something like this:

```
cd reports/TEST
```

Now you can change the report's configuration. SeReTo requires you to set up the **dates**, **targets** and **people** for the report.

### Dates

Run the following command:

```sh
sereto config dates add
```

SeReTo will ask you which date you would like to configure:

* *sow_sent* = date when you will be sending your Statement of Work
* *pentest_ongoing* = pair of dates indicating when the assessment will be performed
* *review* = date when the review is going to be done
* *report_sent* = date when you will be delivering the report to your customer

You then set the dates using the format DD-Mmm-YYYY, such as 18-Apr-2024.

![](assets/sereto-c-d-a.gif)

Run this command multiple times for each type of date you would like to set.

### Targets

Run the following command:

```sh
sereto config targets add
```

SeReTo will ask you about some details you would like to set. Make sure to include all necessary details, such as destination IP addresses (dst_ips), source IP addresses (src_ips), list of URLs etc.

![](assets/sereto-c-t-a.gif)

Run this command multiple times for each target.


### People

Run the following command:

```sh
sereto config people add
```

SeReTo will let you choose the role (type) and details of the person you are currently setting.

Run this command multiple times for each person you would like to set.


## Adding Findings To A Target

Find the directory of your target in your report's directory. The name of the target's directory should look like the following: `target_<category>_<target_unique_name>`. For example *target\_dast\_DBserver*. You will find a *findings.yaml* file in this directory. Open it in your editor.

In the top of the findings.yaml file you can find an example of how to include a finding. Top level findings are called **Group Findings**. Each Group Finding has its name, in the following example the name is *Misconfigured HTTP Headers*. Each Group Finding also has one or more **Nested Findings**. In the following example these are *HSTS Header Not Set* (which has the ID "hsts_not_set") and *Weakly Configured CSP Header* ("weak_csp").

```yaml
report_include:
- name: "Misconfigured HTTP Headers"
  findings:
  - "hsts_not_set"
  - "weak_csp"
```

List all the Group Findings you would like to include in your report under the *report_include* directive. You can copy the identifiers of Nested Findings from the second section of findings.yaml (under "All discovered findings from the templates").

Individual Findings may require you to fill in extra information, such as screenshots, which will be used to customize the finding in automated way. Fill these in the second section of the *findings.yaml*. Manual editing of the findings is still possible.
