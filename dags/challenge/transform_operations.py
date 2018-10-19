
import datetime
import gc
import logging
import os
import pandas as pd

from dags import challenge as c


log = logging.getLogger(__name__)

# final DataFrame that will be result from the entire merge of
# transformed json new files
merged_df = pd.DataFrame()


class TransformOperations:
    """handles functionality for flattening CSVs."""

    # store the current directory of the airflow home folder
    # airflow creates a home environment variable pointing to the location
    HOME_DIRECTORY = str(os.environ['HOME'])

    @classmethod
    def transform_headlines_to_csv(cls,
                                   pipeline_information=None,
                                   tf_json_func=None,
                                   tf_key_json_func=None,
                                   **context):
        """converts the jsons in a given directory to csv.

        Use different transformation methods depending on the
        current active pipeline.

        For the 'tempus_challenge_dag' pipeline, the function
        `transform_news_headlines_to_csv` is used via a helper-function
        `helper_execute_json_transformation`.

        For the 'tempus_bonus_challenge_dag' pipeline, the function
        `transform_keyword_headlines_to_csv` is used via a helper-function
        `helper_execute_keyword_json_transformation`.

        The end transformations are stored in the respective 'csv'
        datastore folders of the respective pipelines.

                Pipeline 1  CSV: Tempus Challenge DAG
        For the 'tempus_challenge_dag' pipeline all the news headlines
        from all the english sources are flattened and transformed into
        one single csv file, the pipeline execution date is appended to
        the end transformed csv. It is of the form:
        `pipeline_execution_date`_headlines.csv

                Pipeline 2 CSVs: Tempus Bonus Challenge DAG
        For each the four keywords queries of the 'tempus_bonus_challenge_dag'
         - 'Tempus Labs', 'Eric Lefkofsky', 'Cancer', 'Immunotheraphy' - the
        result is four separate csv files, each representing all the headlines
        about that particular keyword. The pipeline execution date is appended
        to the end transformed csv's. The keyword headline files are of form:
        `pipeline_execution_date`_`keyword`_`headlines`.csv

        #  Arguments:
            :param pipeline_information: object that provide more information
                about the current pipeline. Defaults to the NewsInfoDTO class.
            :type pipeline_information: object
            :param context: Airflow context object reference to the current
                pipeline.
            :type info_func: dict
            :param tf_json_func: function for transformaing the json
                headline files in the 'headlines' directory of the
                'tempus_challenge_dag' pipeline
            :type tf_json_func: function
            :param tf_key_json_func: function for transformaing the json
                headline files in the 'headlines' directory of the
                'tempus_bonus_challenge_dag' pipeline
            :type tf_key_json_func: function
        """

        log.info("Running transform_headlines_to_csv method")

        # Function Aliases
        # use an alias since the length of the real function call when used
        # is more than PEP-8's 79 line-character limit.
        if not tf_json_func:
            tf_json_func = cls.helper_execute_json_transformation
        if not tf_key_json_func:
            tf_key_json_func = cls.helper_execute_keyword_json_transformation

        # get active pipeline information
        pipeline_name = context['dag'].dag_id
        if not pipeline_information:
            pipeline_information = NewsInfoDTO

        pipeline_info = pipeline_information(pipeline_name)
        headline_dir = pipeline_info.headlines_directory

        # execution date of the current pipeline
        exec_date = str(context['execution_date'])

        # transformation operation status
        transform_status = None

        # perform context-specific transformations
        if pipeline_name == "tempus_challenge_dag":
            # transform all jsons in the 'headlines' directory
            transform_status = tf_json_func(headline_dir, exec_date)
            return transform_status
        elif pipeline_name == "tempus_bonus_challenge_dag":
            # transform all jsons in the 'headlines' directory
            transform_status = tf_key_json_func(headline_dir, exec_date)
            return transform_status
        else:
            # the active pipeline is not one of the two we developed for.
            print("This pipeline {} is not valid".format(pipeline_name))
            # log this issue in Airflow and return an error status
            log.info("This pipeline {} is not valid".format(pipeline_name))
            return False

    @classmethod
    def helper_execute_keyword_json_transformation(cls,
                                                   directory,
                                                   timestamp=None):
        """runs a block of code to transform keyword json headlines to csv.

        # Arguments:
            :param directory: directory having the jsons to
                execute a transformation on.
            :type directory: str
            :param timestamp: date of the pipeline execution that
                should be appended to created csv files
            :type timestamp: datetime object
        """

        log.info("Running helper_execute_keyword_json_transformation method")

        # transformation operation status
        status = None

        # the name the created csv file should be given
        fname = None

        # execution date cannot be None
        if not timestamp:
            timestamp = datetime.datetime.now()

        # transform individual jsons in the 'headlines' directory into
        # individual csv files
        files = None

        if os.listdir(directory):
            files = [file for file in os.listdir(directory)
                     if file.endswith('.json')]

        # check existence of json files before beginning transformation
        if not files:
            raise NoFilesFoundError("Directory has no json-headline files")
        else:
            for file in files:
                key = file.split("_")[1]
                fname = str(timestamp) + "_" + key + "_top_headlines.csv"
                status = cls.transform_keyword_headlines_to_csv(file, fname)

        return status

    @classmethod
    def helper_execute_json_transformation(cls,
                                           directory,
                                           timestamp=None,
                                           json_to_csv_func=None,
                                           jsons_to_df_func=None,
                                           df_to_csv_func=None):
        """runs a block of code to transform json headlines to csv.


        A number of performance issues need to be considered for this task:

        The intent of the code is combined multiple jsons files into one csv.
        This could be done using Pandas's DataFrame object
        as an intermediary format - performing the merge in DataFrames
        as a stream OR as a batch (both which have their memory tradeoffs)
        This could also be done using csv's - by converting each json file
        # into a csv and doing the merger there (also as either stream OR
        # batch) using for example Python's CSV.

        Memory Tradeoffs Notes:
        We work with the assumption that processing all these jsons together
        at once isn't possible - especially in case of json data sets that
        don't fit into memory (even if we optimized types and filtered some
        of the data). In this instance, a better strategy will be to make the
        transformation in chunks (or batches); turning a portion into
        DataFrames in memory and merging, till we have all the jsons merged
        as a single DataFrame.


        Though as the author, I am familiar with both Pandas and CSV libraries,
        I decided to use Pandas - due to it being, in my opinion, more
        powerful than the mere CSV library. Pandas also uses the CSV library
        internal and has highly flexible functions for manipulating both
        json and csv data.

        I decided to use Pandas's DataFrame object as the intermediary format
        and a Batch merging approach: Transforming the json's, two at a time
        (i.e. pairwise merging), into DataFrames and merging them, after which
        the old DataFrames are cleaned up in memory before the next
        transform-merge iteration; till the whole transformed jsons are merged
        into one single DataFrame.

        The time complexity of doing a sequential merge (of the news json
        files) is O(n) which would become a problem to do as the number of
        files grow.

        An alternative approach follows from the principles in the traditional
        Merge Sort algorithm - whose time complexity in the best, average, and
        worst cases are O(n logn) - Space complexity worst case is O(n)
        http://bigocheatsheet.com/

        From an algorithmic time complexity standpoint, however, O(n) is better
        than O(n logn). But, more efficient merge-method will be needed when
        dealing with larger file sizes.

        # Arguments:
            :param directory: directory having the jsons to
                execute a transformation on.
            :type directory: str
            :param timestamp: date of the pipeline execution that
                should be appended to created csv files
            :type timestamp: datetime object
            :param json_to_csv_func: function that transforms a single news
                json file into a csv
            :type json_to_csv_func: function
            :param jsons_to_df_func: function that transforms a set of news
                json files into intermediary DataFrames and merges them into
                one final DataFrame
            :type jsons_to_df_func: function
            :param df_to_csv_func: function that transforms a single DataFrame
                into a csv file
        """

        log.info("Running helper_execute_json_transformation method")

        # Function Aliases
        # use an alias since the length of the real function call when used
        # is more than PEP-8's 79 line-character limit.
        if not json_to_csv_func:
            json_to_csv_func = cls.transform_news_headlines_json_to_csv
        if not jsons_to_df_func:
            jsons_to_df_func = cls.transform_jsons_to_dataframe_merger
        if not df_to_csv_func:
            df_to_csv_func = cls.transform_headlines_dataframe_to_csv

        # transformation operation status
        status = None

        # execution date cannot be None
        if not timestamp:
            timestamp = datetime.datetime.now()

        # the name the created csv file should be given
        filename = str(timestamp) + "_top_headlines.csv"

        # reference to the final merged dataframes of the json files
        merged_dataframe = pd.DataFrame()

        # transform individual jsons in the 'headlines' directory into one
        # single csv file
        files = []

        if not os.listdir(directory):
            raise FileNotFoundError("Directory is empty")

        if os.listdir(directory):
            files = [file for file in os.listdir(directory)
                     if file.endswith('.json')]

        # check existence of json files before beginning transformation
        if not files:
            raise FileNotFoundError("Directory has no json-headline files")

        if len(files) == 1:
            # a single json file exists, perform direct transformation on it.
            status = json_to_csv_func(files[0], filename)
        else:
            # transform the json files into DataFrames and merge them into one.
            merged_dataframe = jsons_to_df_func(files)
            # transform the merged DataFrame into a csv
            status = df_to_csv_func(merged_dataframe, filename)

        return status

    @classmethod
    def transform_jsons_to_dataframe_merger(cls,
                                            json_files,
                                            extract_func=None,
                                            transform_func=None,
                                            read_js_func=None):
        """transforms a set of json files into a DataFrames and merges all of
        them into one.

        # Arguments:
            :param json_files: a list of json files to be processed.
            :type json_files: list
            :param extract_func: the function used to extract news data
                from a dataframe
            :type extract_func: function
            :param transform_func: the function used to transform news
                data into a dataframe
            :type transform_func: function
            :param read_js_fnc: the function used to read-in and process the
                json file. By Default is the Pandas read_json() function
            :type read_js_func: function
        """

        log.info("Running transform_jsons_to_dataframe_merger method")

        # Function Aliases
        # use an alias since the length of the real function call when used
        # is more than PEP-8's 79 line-character limit.
        if not extract_func:
            extract_func = c.ExtractOperations.extract_news_data_from_dataframe
        if not transform_func:
            transform_func = cls.transform_data_to_dataframe
        if not read_js_func:
            read_js_func = pd.read_json

        # perform pairwise transformation of the json files into DataFrames
        # and their subsequent merging into a single DataFrame.
        current_file_df = None

        # To perform continous pairwise merging of the dataframe-transformed
        # json files in the directory, we need a way to keep track of what has
        # been merged so far. There needs to be a way to maintain state.
        # This (empty) DataFrame is created for that purpose and is made into
        # a global Python object within this module/python file.
        #
        # Use of global variables might not be the ideal way to handle this, as
        # they are generally discouraged in several development
        # environs/instances due to the kinds of unpredictable bugs they
        # potentially create - most especially in multithreaded environments)
        #
        # Hence, our use of the `global` keyword here for this operation is
        # ONLY time it will ever be used in this project.
        #
        # An alternative, to consider, might be to make use of Airflow's
        # Variable class to store the state of object.
        #
        # Another alternative, to consider, asides global variables is the use
        # of Python (function) closures to achieve state maintenance.
        global merged_df

        for indx, file in enumerate(json_files):
            # perform json to DataFrame transformations by function-chaining
            log.info(json_files[indx])
            current_file_df = transform_func(extract_func(
                                             read_js_func(json_files[indx],
                                                          lines=True)))

            # perform merge
            merged_df = pd.concat([merged_df, current_file_df])
            # free up memory by clearing the previously transformed DataFrames
            del current_file_df
            # force Python's Garbage Collector to clean up unused variables and
            # free up memory manually
            gc.collect()

        # return a merged DataFrame of all the jsons
        return merged_df

    @classmethod
    def transform_news_headlines_json_to_csv(cls,
                                             json_file,
                                             csv_filename=None,
                                             extract_func=None,
                                             transform_func=None,
                                             read_js_func=None):
        """transforms the json contents of a given file into a csv.

        The function specifically operates on jsons in the 'headlines'
        folder of the 'tempus_challenge_dag' pipeline.

        Uses the Pandas library to parse, traverse and flatten the
        json data into a csv file.

        # Arguments:
            :param json_file: a json file containing top news headlines
                based on a keyword
            :type json_file: file
            :param csv_filename: the filename of the transformed csv
            :type csv_filename: str
            :param extract_func: the function used to extract news data
                from a dataframe
            :type extract_func: function
            :param transform_func: the function used to transform news
                data into a dataframe
            :type transform_func: function
            :param read_js_fnc: the function used to read-in and process the
                json file. By Default is the Pandas read_json() function
            :type read_js_func: function
        """

        log.info("Running transform_news_headlines_json_to_csv method")

        # Function Aliases
        # use an alias since the length of the real function call when used
        # is more than PEP-8's 79 line-character limit.
        if not extract_func:
            extract_func = c.ExtractOperations.extract_news_data_from_dataframe
        if not transform_func:
            transform_func = c.TransformOperations.transform_data_to_dataframe
        if not read_js_func:
            read_js_func = pd.read_json

        # use Pandas to read in the json file
        keyword_data = read_js_func(json_file, lines=True)

        # extraction and intermediate-transformation of the news json
        data = extract_func(keyword_data)
        transformed_df = transform_func(data)

        # transform to csv and save in the 'csv' datastore
        csv_dir = c.FileStorage.get_csv_directory("tempus_challenge_dag")
        if not csv_filename:
            csv_filename = "sample.csv"
        csv_save_path = os.path.join(csv_dir, csv_filename)
        transformed_df.to_csv(csv_save_path)

        # ensure status of operation is communicated to caller function
        op_status = None
        if os.listdir(csv_dir):
            log.info("english news headlines csv saved in {}".format(csv_dir))
            op_status = True
        else:
            op_status = False

        return op_status

    @classmethod
    def transform_headlines_dataframe_to_csv(cls, frame, csv_filename):
        """flatten's a given dataframe into a csv file.

         # Arguments:
            :param frame: single DataFrame consisting of all english news
                sources headlines
            :type frame: DataFrame
            :param csv_filename: the filename of the transformed csv
            :type csv_filename: str
        """

        log.info("Running transform_headlines_dataframe_to_csv method")

        # input is a single DataFrame consisting of all english news sources
        # headlines
        transformed_df = frame

        # transform to csv and save in the 'csv' datastore
        csv_dir = c.FileStorage.get_csv_directory("tempus_challenge_dag")
        if not csv_filename:
            csv_filename = "sample.csv"
        csv_save_path = os.path.join(csv_dir, csv_filename)
        transformed_df.to_csv(path_or_buf=csv_save_path)

        # ensure status of operation is communicated to caller function
        op_status = None
        if os.listdir(csv_dir):
            log.info("english news headlines csv saved in {}".format(csv_dir))
            op_status = True
        else:
            op_status = False

        return op_status

    @classmethod
    def transform_key_headlines_to_csv(cls,
                                       json_file,
                                       csv_filename=None,
                                       extract_func=None,
                                       transform_func=None,
                                       reader_func=None):
        """converts the json contents of a given folder into a csv.

        The function specifically operates on jsons in the 'headlines'
        folder of the 'tempus_bonus_challenge_dag' pipeline.

        Uses the Pandas library to parse, traverse and flatten the
        json data into a csv file.

        # Arguments:
            :param json_file: a json file containing top news headlines
                based on a keyword
            :type json_file: file
            :param csv_filename: the filename of the transformed csv
            :type csv_filename: str
            :param extract_func: the function used to extract news keyword
                fields from a dataframe
            :type extract_func: function
            :param transform_func: the function used to transform news keyword
                data into a dataframe
            :type transform_func: function
            :param reader_func: the function used to read-in and process the
                json file. By Default is the Pandas read_json() function
            :type reader_func: function
        """

        log.info("Running transform_key_headlines_to_csv method")

        # Function Aliases
        # use an alias since the length of the real function call when used
        # is more than PEP-8's 79 line-character limit.
        if not extract_func:
            extract_func = c.ExtractOperations.extract_news_data_from_dataframe
        if not transform_func:
            transform_func = c.TransformOperations.transform_data_to_dataframe

        # use Pandas to read in the json file
        if not reader_func:
            reader_func = pd.read_json
        keyword_data = reader_func(json_file, lines=True)

        # extraction and intermediate-transformation of the news json
        data = extract_func(keyword_data)
        transformed_df = transform_func(data)

        # transform to csv and save in the 'csv' datastore
        csv_dir = c.FileStorage.get_csv_directory("tempus_bonus_challenge_dag")
        if not csv_filename:
            csv_filename = str(datetime.datetime.now()) + "_" + "sample.csv"
        csv_save_path = os.path.join(csv_dir, csv_filename)
        transformed_df.to_csv(csv_save_path)

        # ensure status of operation is communicated to caller function
        op_status = None
        query_key = csv_filename.split("_")[1]
        if os.path.isfile(csv_save_path):
            log.info("{} headlines csv saved in {}".format(query_key, csv_dir))
            op_status = True
        else:
            log.info("{} headlines could not be saved in {}".format(query_key,
                                                                    csv_dir))
            op_status = False

        return op_status

    @classmethod
    def transform_data_to_dataframe(cls, news_data):
        """converts a dictionary of news data into a Pandas Dataframe.

        # Arguments:
            :param news_data: extracted news data information.
            :type news_data: dict
        """

        log.info("Running transform_data_to_dataframe method")

        # error-check
        if not news_data:
            raise ValueError("news data argument cannot be empty")

        field_names = ['news_source_id',
                       'news_source_name',
                       'news_author',
                       'news_title',
                       'news_description',
                       'news_url',
                       'news_image_url',
                       'news_publication_date',
                       'news_content']

        # craft the transformed dataframe
        news_df = pd.DataFrame()

        # populate the columns of the dataframe with news data
        for index, field in enumerate(list(news_data.keys())):
            news_df[field_names[index]] = news_data[field]

        return news_df
