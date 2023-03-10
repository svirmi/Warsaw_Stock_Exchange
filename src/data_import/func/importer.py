"""The module importing data from websites."""

from ast import literal_eval as leval
import math
import re
from bs4 import BeautifulSoup as bs
import numpy as np
import pandas as pd
from progress.bar import PixelBar as pb
import requests

def company_importer(url):
    """The function importing dictionary of companies' codes from url."""

    # Cooking the soup...
    tab = bs(
        requests.get(
            url,
            timeout = 100
        ).text,
        'lxml'
    ).find('table')

    # Gathering dictionary of companies from table
    comp_dict = {}

    with pb('Gathering companies...', suffix = '%(percent)d%%') as pixel_bar:
        for rows in tab.find_all('a', {'class': 's_tt'}):
            comp_dict[(rows.get('href').replace('/notowania/', ''))] = []
            pixel_bar.next()

    print('Gathering companies is finished!')

    return comp_dict

def date_converter(date):
    """Subfunction converting date."""
    # Input format: dd.mm.yyyy
    # Output format: yyyy/QQ
    # If date is not quarter date (i.e. March/June/September/December)
    # function would return 'invalid_date' to prevent passing data from this period

    # Dict of dates
    date_dict = {
        '03':'Q1',
        '06':'Q2',
        '09':'Q3',
        '12':'Q4'
    }

    if date[3:5] in date_dict:
        return date[6:] + '/' + date_dict[date[3:5]]

    return 'invalid_date'

def dynamics(newer_val, older_val):
    """Function to handle dynamics calculation"""
    # E.g. newer_val is value for Q1/2020,
    # older_val is value for Q1/2019.
    # Then output is dynamics between older_val and newer_val
    # Handling 0 values is added

    if not np.isnan(newer_val):
        if older_val == 0 and newer_val != 0:
            return newer_val / 10 ** -(int(math.log10(abs(newer_val))) + 1)
        if older_val == 0 and newer_val == 0:
            return 0
        return (newer_val - older_val) / abs(older_val)
    return math.nan

def tab_finder(url, section_type, class_type):
    """Function looking for table in website."""
    # Input values are URL, section type (e.g. table, div),
    # class type (e.g. report-table, qTableFull)
    # Output is table found in website

    return bs(
        requests.get(url, timeout = 100).content,
        'lxml'
    ).find(section_type, {'class':class_type})

def quarters_changer(start, steps):
    """Function to look for quarter n steps back/forward"""
    # I.e. for start = '2020/Q1' and steps = 2 it would return '2020/Q3'

    current_year = leval(start[:4])
    current_quarter = leval(start[-1:])

    step_quarter = (current_quarter + steps) % 4

    if step_quarter == 0:
        step_quarter = 4

    if steps >= 0:
        step_year = int(np.floor(steps / 4 + (current_quarter - step_quarter) / 4))
    else:
        step_year = int(np.ceil(steps / 4 + (current_quarter - step_quarter) / 4))

    return "/".join([
        str(current_year + step_year),
        'Q' + str(step_quarter)
    ])

def var_dynamics(data_frame):
    """Function adding y/y dynamics of various variables."""
    # For each column in data frame a y/y dynamics would be calculated.
    # E.g. y/y change for Q1 2020 is dynamics against Q1 2019

    quarters, dynamics_dict = [], {}

    for row_name in data_frame.index.values:
        older_quarter = quarters_changer(row_name, -4)
        if older_quarter in data_frame.index:
            quarters.append(row_name)
            for col_name, _ in data_frame.items():
                new_col_name = col_name + '_yy'
                if new_col_name not in dynamics_dict:
                    dynamics_dict[new_col_name] = []
                dynamics_dict[new_col_name].append(
                    dynamics(
                        data_frame.at[row_name, col_name],
                        data_frame.at[older_quarter, col_name]
                    )
                )

    return pd.DataFrame(dynamics_dict, index = quarters)

class CompanyDF():
    """Data frame with single company data"""

    def __init__(self, code, features_dict):
        self.code = code
        self.features_dict = features_dict

    def regular_importer(self, url):
        """Function to deal with regular tabs."""
        # Input is URL for each table for given company code (except dividends table)

        def tab_head(tab):
            """Subfunction processing table head."""
            # Input is website's table, function extracts quarters from table head

            quarters = [
                re.sub(
                    r'\s+', '', quarter.text
                )[:7] for quarter in tab.find_all('th', {'class':'thq h'})
            ]
            quarters.append(
                re.sub(
                    r'\s+', '',
                    tab.find_all('th', {'class':'thq h newest'})[0].text
                )[:7]
            )

            # Some companies reported only once a year in given quarter.
            # Hence head of their table looks like years, not quarters.
            if quarters[0][4] != '/':
                quarters_dict = {
                    '(ma':'/Q1',
                    '(cz':'/Q2',
                    '(wr':'/Q3',
                    '(gr':'/Q4'
                }
                quarters = [quarter[:4] + quarters_dict[quarter[4:]] for quarter in quarters]

            return quarters

        def cell_cleaner(cell):
            """Subfunction clearing table's cells."""
            # Input is table cell, function extracts only value
            # without comments or unnecessary additions

            temp_cell = cell.text.replace(' ', '').replace('~', '')

            if re.search('[a-zA-Z]', temp_cell):
                temp_cell = temp_cell[:re.search('[a-zA-Z]', temp_cell).start()]

            if not temp_cell:
                result = math.nan
            elif '%' in temp_cell:
                result = leval(temp_cell[:-1]) / 100
            else:
                result = leval(temp_cell)

            return result

        tab = tab_finder(url, 'table', 'report-table')
        # Gathering list of quarters from table
        quarters, temp_data_dict, code_data_dict = [], {}, {}
        if tab:
            quarters = tab_head(tab)

            # Gathering rest of table
            for row in tab.find_all('tr'):
                # Workaround for omitting row with quarters
                if row.find('td', {'class':'f'}):
                    row_name = row.find('td', {'class':'f'}).text
                else:
                    row_name = ''

                # Gathering data from given row
                if row_name and row_name != 'Data publikacji':
                    temp_data_dict[row_name] = []

                    for cell in row.find_all('td', {'class':'h'}):
                        # Some data clearing
                        temp_data_dict[row_name].append(cell_cleaner(cell))

            # Changing column names to codes
            for key, _ in temp_data_dict.items():
                if key in self.features_dict.keys():
                    code_data_dict[self.features_dict[key]] = temp_data_dict[key]
                else:
                    code_data_dict[key] = temp_data_dict[key]

        return code_data_dict, quarters

    def regular_addition(self, data_frame, data_dict, quarters, iteration):
        """Function adding various 'dynamics' variables."""
        # Added dynamics varies depending on which table is actually processed
        # For all tables it would be var_dynamics
        # For market value indices it would be also price_dynamics
        # For profit and loss account it would be also guru_dynamics


        def price_dynamics(data_frame, comp_code):
            """Subfunction adding max price dynamics in the next year to data frame."""
            # Max price dynamics in the next year is target feature for analysis.
            # It means, e.g.: for Q1 2020, what was the maximum price in the following year?
            # I.e. we want to get max value for [Q2 2020, Q3 2020, Q4 2020, Q1 2021]
            # and then calculate % change between this max value and value for Q1 2020

            # Additionaly: 6M dynamics of price for calculating relative strength
            # This is simpler, e.g.: for Q1 2020 it would be dynamics between Q3 2019 and Q1 2020

            quarters = []
            dynamics_dict = {
                'quarter':[],
                'company_code':[],
                'max_price_change_y':[],
                'price_change_6m':[]
            }

            for row_name in data_frame.index.values:
                older_quarter = quarters_changer(row_name, -2)
                newer_quarters = [quarters_changer(row_name, i) for i in range(1, 5)]
                newer_quarters_val = []

                for quarter in newer_quarters:
                    if quarter in data_frame.index:
                        newer_quarters_val.append(data_frame.at[quarter, 'price'])

                if newer_quarters_val:
                    quarters.append(row_name)
                    dynamics_dict['max_price_change_y'].append(
                        dynamics(max(newer_quarters_val), data_frame.at[row_name, 'price'])
                    )
                    dynamics_dict['quarter'].append(row_name)
                    dynamics_dict['company_code'].append(comp_code)

                    if older_quarter in data_frame.index:
                        dynamics_dict['price_change_6m'].append(
                            dynamics(
                                data_frame.at[row_name, 'price'],
                                data_frame.at[older_quarter, 'price']
                            )
                        )
                    else:
                        dynamics_dict['price_change_6m'].append(np.nan)

            return pd.DataFrame(dynamics_dict, index = quarters)

        def guru_dynamics(data_frame):
            """Subfunction adding changes of various variables for guru strategies."""
            # This function adds values of net_earnings and sales_revenues in previous quarters.
            # 1Q - one quarter before current, 2Q - two quarters before current etc.
            # 5Y - five years before current quarter.

            quarters = []
            dynamics_dict = {
                'net_earnings_1Q':[],
                'net_earnings_2Q':[],
                'net_earnings_5Q':[],
                'net_earnings_6Q':[],
                'sales_revenues_1Q':[],
                'sales_revenues_2Q':[],
                'sales_revenues_5Q':[],
                'sales_revenues_6Q':[],
                'net_earnings_5Y':[]
            }

            for row_name in data_frame.index.values:
                quarters_dict = {
                    '1Q':quarters_changer(row_name, -1),
                    '2Q':quarters_changer(row_name, -2),
                    '5Q':quarters_changer(row_name, -5),
                    '6Q':quarters_changer(row_name, -6),
                    '5Y':quarters_changer(row_name, -60)
                }

                if all(
                    quarter in data_frame.index for quarter in quarters_dict.values()
                ):
                    quarters.append(row_name)
                    for key, value in dynamics_dict.items():
                        if key[:-3] in data_frame.items():
                            value.append(
                                data_frame.at[quarters_dict[key[-2:], key[:-3]]]
                            )
                        else:
                            value.append(np.nan)

            return pd.DataFrame(dynamics_dict, index = quarters)

        if iteration == 0:
            price_dynamics_df = price_dynamics(data_frame, self.code)
            var_dynamics_df = var_dynamics(data_frame)
            data_frame = price_dynamics_df.join(data_frame)
            data_frame = data_frame.join(var_dynamics_df)
        else:
            sub_df = pd.DataFrame(data_dict, index = quarters)
            var_dynamics_df = var_dynamics(sub_df)
            if iteration == 6:
                guru_df = guru_dynamics(sub_df)
            data_frame = data_frame.join(sub_df)
            data_frame = data_frame.join(var_dynamics_df)
            if iteration == 6:
                data_frame = data_frame.join(guru_df)

        return data_frame

    def dividend_importer(self, url, data_frame):
        """Function importing dividends table."""
        # Special importer for dividends table

        # Initiate dividends dict
        years, dividends, div_dict = [], [], {'quarter':[], 'dividend':[]}

        # Cooking the soup...
        div = tab_finder(url, 'div', 'table-c')
        if div:
            for row in div.find('table').find_all('tr'):
                if row.find('td'):
                    years.append(row.find_all('td')[0].text)
                    dividend = row.find(
                        'td', {'class':'status'}
                    ).text.replace('\n', '').replace('\t', '')
                    if dividend == 'wyp??acona':
                        dividends.append(1)
                    else:
                        dividends.append(0)

            for i, year in enumerate(years):
                for val in range(1, 5):
                    div_dict['quarter'].append(str(leval(year) + 1) + '/Q' + str(val))
                    div_dict['dividend'].append(dividends[i])

            div_df = pd.DataFrame(
                div_dict['dividend'],
                index = div_dict['quarter'],
                columns=['dividend_1Y']
            )

            data_frame = data_frame.join(div_df)
        else:
            data_frame['dividend_1Y'] = 0

        return data_frame

class EcoDF():
    """Data frame with economic data"""

    def __init__(self, features_dict):
        self.features_dict = features_dict

    def eco_importer(self, url, row_name):
        """Function handling economic data from biznesradar.pl"""
        # Input is URL for various tables with economic data
        # row_name indicates feature gained from table

        # Initialization of data lists
        quarters, data = [], []

        # Gathering data from sub url
        page = 1
        tab = tab_finder(url + ',' + str(page), 'table', 'qTableFull')
        while tab:
            for row in tab.find_all('tr')[1:]:
                date_str = date_converter(row.find_all('td')[0].text)
                if date_str != 'invalid_date':
                    quarters.append(date_str)
                    data.append(leval(row.find_all('td')[1].text))
            page += 1
            tab = tab_finder(url + ',' + str(page), 'table', 'qTableFull')

        temp_df = pd.DataFrame(data, index=quarters)
        temp_df.columns = [self.features_dict[row_name]]

        return temp_df

    def indices_importer(self, quarters):
        """Function handling WIG and USD/PLN data"""
        # Additional importer for WIG and USD/PLN data
        # These tables have different format than other (they have daily, not quaterly data)

        def tab_importer(url, row_name):
            """Subfunction importing data from url"""

            print(f'Importing {row_name}...')
            # Initialization of data lists
            quarters, data = [], []

            # Gathering data from sub url
            page = 1
            tab = tab_finder(url + ',' + str(page), 'table', 'qTableFull')
            prev_month, current_month = '', ''
            while tab:
                print(f'page {page}...')
                for row in tab.find_all('tr')[1:]:
                    current_month = row.find_all('td')[0].text[3:5]
                    current_date = date_converter(row.find_all('td')[0].text)
                    if current_month != prev_month and current_date != 'invalid_date':
                        date_str = current_date
                        quarters.append(date_str)
                        if row_name == 'usd_pln':
                            data.append(leval(row.find_all('td')[1].text))
                        else:
                            data.append(leval(row.find_all('td')[4].text))
                    prev_month = current_month
                page += 1
                tab = tab_finder(url + ',' + str(page), 'table', 'qTableFull')

            temp_df = pd.DataFrame(data, index=quarters)
            temp_df.columns = [row_name]

            print(f'Importing {row_name} is finished!')

            return temp_df

        def wig_dynamics(data_frame):
            """Subfunction adding 6M dynamics of WIG."""
            # Additionaly: 6M dynamics of WIG for calculating relative strength
            # For Q1 2020 it would be dynamics between Q3 2019 and Q1 2020

            # Initialization of data lists
            quarters, data = [], []

            for row_name in data_frame.index.values:
                older_quarter = quarters_changer(row_name, -2)

                quarters.append(row_name)
                if older_quarter in data_frame.index:
                    data.append(
                        dynamics(
                            data_frame.at[row_name, 'wig'],
                            data_frame.at[older_quarter, 'wig']
                        )
                    )
                else:
                    data.append(np.nan)

            temp_df = pd.DataFrame(data, index = quarters)
            temp_df.columns = ['wig_6m']

            return temp_df

        indices_df = pd.DataFrame(index=quarters)

        usd_df = tab_importer(
            'https://www.biznesradar.pl/notowania-historyczne/USD-DOLAR',
            'usd_pln'
        )

        wig_df = tab_importer(
            'https://www.biznesradar.pl/notowania-historyczne/WIG',
            'wig'
        )

        for data_frame in [
            usd_df, wig_df, var_dynamics(usd_df), var_dynamics(wig_df), wig_dynamics(wig_df)
        ]:
            indices_df = pd.merge(
                indices_df, data_frame, how='left', left_index=True, right_index=True
            )

        return indices_df

class FinalDF():
    """Final data frame"""
    # These data frame contains companies and economic data
    # plus other additions for guru strategies

    def __init__(self, companies_df, eco_df):
        self.companies_df = companies_df
        self.eco_df = eco_df

    def merger(self):
        """Function merging companies' and economic dfs"""

        # Merging dfs
        final_df = pd.merge(
            self.companies_df,
            self.eco_df,
            left_on='quarter',
            right_index=True
        )

        return final_df

    def guru_features(self, data_frame):
        """Function adding various features for guru strategies"""

        # Dictionary of variables to divide
        # Key is new variable name
        # Value is list: [dividend, divisor]
        div_dict = {
            'capitalization_usd':['capitalization', 'usd_pln'],
            'relative_strength_6m':['price_change_6m', 'wig_6m'],
            'price_earnings_net_earnings':['price_earnings', 'net_earnings'],
            'roce':['ebit', 'core_capital'],
            'net_debt_ebit':['net_debt', 'ebit'],
            'current_assets_short_term_liabilities':['current_assets', 'short_term_liabilities'],
            'long_term_liabilities_net_working_capital':[
                'long_term_liabilities', 'net_working_capital'
            ]
        }

        # Ranking variables
        # Key is new variable name
        # Value is variable on which the ranking is based

        # Ascending rank dict:
        asc_dict = {
            'rank_ev_ebit':'ev_ebit',
            'rank_price_sales_revenues':'price_sales_revenues',
            'rank_price_earnings':'price_earnings'
        }

        # Descending rank dict:
        desc_dict = {
            'rank_roic':'roic',
            'rank_relative_strength_6m':'relative_strength_6m',
            'rank_ebit_yy':'ebit_yy'
        }

        # Capitalization
        data_frame['capitalization'] = data_frame.apply(
            lambda row: row.number_of_shares * row.price,
            axis=1
        )

        # Division of various features
        for key, value in div_dict.items():
            dividend_index = data_frame.columns.get_loc(value[0])
            divisor_index = data_frame.columns.get_loc(value[1])
            division = []

            # Yes, I know it's anti-pattern - but it's needed for proper division
            for index, _ in data_frame.iterrows():
                dividend = data_frame.iloc[index, dividend_index]
                divisor = data_frame.iloc[index, divisor_index]
                if not np.isnan(dividend):
                    if divisor == 0 and dividend != 0:
                        division.append(
                            dividend / 10 ** -(int(math.log10(abs(dividend))) + 1)
                        )
                    if divisor == 0 and dividend == 0:
                        division.append(0)
                    division.append(dividend / divisor)
                division.append(math.nan)

            data_frame[key] = pd.Series(division)

        # Ascending rankings
        for key, value in asc_dict.items():
            data_frame[key] = data_frame.groupby('quarter')[value].rank(method='dense')

        # Descending rankings
        for key, value in desc_dict.items():
            data_frame[key] = data_frame.groupby('quarter')[value].rank(
                method='dense',
                ascending=False
            )

        # Greenblatt's ranking
        data_frame['greenblatt_rank'] = data_frame.apply(
            lambda row: (row.rank_ev_ebit + row.rank_roic) / 2,
            axis=1
        )
        data_frame['greenblatt_rank'] = data_frame.groupby('quarter')['greenblatt_rank'].rank(
            method='dense',
            ascending=False
        )

        # Average P/E ratio
        avg_price_earnings = pd.DataFrame(data_frame.groupby('quarter')['price_earnings'].mean())
        avg_price_earnings = avg_price_earnings.rename(
            columns={'price_earnings':'avg_price_earnings'}
        )

        data_frame = pd.merge(data_frame, avg_price_earnings, left_on='quarter', right_index=True)

        return data_frame
