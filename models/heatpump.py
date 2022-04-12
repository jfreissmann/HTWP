# -*- coding: utf-8 -*-
"""
Generic heat pump model.

@author: Jonas Freißmann and Malte Fritz
"""

from tespy.components import (
    CycleCloser, Source, Sink, Pump, HeatExchanger, Condenser,
    HeatExchangerSimple, Compressor, Valve
    )
from tespy.connections import Connection
from tespy.networks import Network
import os
import numpy as np
import CoolProp.CoolProp as CP
from tespy.connections import Bus, Ref
from tespy.tools.characteristics import CharLine
from tespy.tools.characteristics import load_default_char as ldc
from fluprodia import FluidPropertyDiagram


class Heatpump():
    """
    Generic heat pump model.

    Parameters
    ----------
    fluids : list
        list containing all fluids in the heat pump topology

    nr_cycles : int
        number of cycles/stages of the heat pump

    int_heatex : dict
        dictionary where each key is the integer index of the cycle of the hot
        side of an internal heat exchanger and the value is either a single
        integer for the cycle of the cold side or a list when multiple
        internal heat exchangers have the hot side of the cycle of the key

    intercooler : dict
        dictionary where each key is the integer index of the cycle in which
        the intercooler(s) are to be placed and where the corresponding value
        is a dictionary with the keys 'amount' (the number of compression
        stages is this number + 1) and 'type' (either 'HeatExchanger' or
        'HeatExchangerSimple')

    kwargs
        currently supported kwargs are the units used for displaying results
        with TESPy (T_unit, p_unit, h_unit and m_unit; see TESPy documentation)

    Note
    ----
    Both for the internal heat exchangers and the intercoolers an integer
    index is used to refer to a cycle/stage of a heatpump. This allows the
    distinct positioning of these components under the premiss that they are
    always placed in certain positions within their respective cycles. For
    intercoolers between compression stages this is trivial, but the internal
    heat exchangers place has to be predeterment for ease of use. From what
    could be gathered from literature these internal heat exchangers are
    used to cool the condensate and preheat the evaporated refrigerant most of
    the time, so this will be the implementation within the model.
    The nomenclature of integer indexes of cycles is also used in the
    labelling of the components.
    """

    def __init__(self, fluids, nr_cycles=1, int_heatex={}, intercooler={},
                 **kwargs):
        self.fluids = fluids
        self.nr_cycles = nr_cycles
        self.int_heatex = int_heatex
        self.intercooler = intercooler

        self.init_network(**kwargs)
        self.components = dict()
        self.generate_components()
        self.connections = dict()
        self.generate_topology()

    def init_network(self, **kwargs):
        """Initialize network."""
        if 'T_unit' in kwargs:
            T_unit = kwargs['T_unit']
        else:
            T_unit = 'C'
        if 'p_unit' in kwargs:
            p_unit = kwargs['p_unit']
        else:
            p_unit = 'bar'
        if 'h_unit' in kwargs:
            h_unit = kwargs['h_unit']
        else:
            h_unit = 'kJ / kg'
        if 'm_unit' in kwargs:
            m_unit = kwargs['m_unit']
        else:
            m_unit = 'kg / s'

        self.nw = Network(
            fluids=self.fluids, T_unit=T_unit, p_unit=p_unit, h_unit=h_unit,
            m_unit=m_unit
            )

    def generate_components(self):
        """Generate necessary components based on topology parametrisation."""
        # Heat Source Feed Flow
        self.components['Heat Source Feed Flow'] = Source(
            'Heat Source Feed Flow'
            )

        # Heat Source Back Flow
        self.components['Heat Source Back Flow'] = Sink(
            'Heat Source Back Flow'
            )

        # Heat Source Recirculation Pump
        self.components['Heat Source Recirculation Pump'] = Pump(
            'Heat Source Recirculation Pump'
            )

        # Heat Source evaporator
        self.components['Evaporator 1'] = HeatExchanger('Evaporator 1')

        # Consumer Cycle Closer
        self.components['Consumer Cycle Closer'] = CycleCloser(
            'Consumer Cycle Closer'
            )

        # Consumer Recirculation Pump
        self.components['Consumer Recirculation Pump'] = Pump(
            'Consumer Recirculation Pump'
            )

        # Consumer
        self.components['Consumer'] = HeatExchangerSimple('Consumer')

        for cycle in range(1, self.nr_cycles+1):
            # Cycle closer for each cycle
            self.components[f'Cycle Closer {cycle}'] = CycleCloser(
                f'Cycle Closer {cycle}'
                )

            # Valve for each cycle
            self.components[f'Valve {cycle}'] = Valve(f'Valve {cycle}')

            if cycle != 1:
                # Heat exchanger between each cycle
                self.components[f'Heat Exchanger {cycle-1}_{cycle}'] = (
                    HeatExchanger(f'Heat Exchanger {cycle-1}_{cycle}')
                    )

            if cycle == self.nr_cycles:
                # Condenser in the upper most cycle
                self.components[f'Condenser {cycle}'] = Condenser(
                    f'Condenser {cycle}'
                    )

            # Intercoolers where they are placed by user
            if cycle in self.intercooler.keys():
                nr_intercooler = self.intercooler[cycle]['amount']
                ic_type = self.intercooler[cycle]['type']
                for i in range(1, nr_intercooler+2):
                    if i < nr_intercooler+1:
                        if ic_type == 'HeatExchanger':
                            self.components[f'Intercooler {cycle}-{i}'] = (
                                HeatExchanger(f'Intercooler {cycle}-{i}')
                                )
                        elif ic_type == 'HeatExchangerSimple':
                            self.components[f'Intercooler {cycle}-{i}'] = (
                                HeatExchangerSimple(f'Intercooler {cycle}-{i}')
                                )

                    # Necessary amount of compressors due to intercoolers
                    self.components[f'Compressor {cycle}-{i}'] = Compressor(
                        f'Compressor {cycle}_{i}'
                        )
            else:
                # Single compressors for each cycle without intercooler
                self.components[f'Compressor {cycle}'] = Compressor(
                        f'Compressor {cycle}'
                        )

            if cycle in self.int_heatex.keys():
                if type(self.int_heatex[cycle]) == list:
                    for target_cycle in self.int_heatex[cycle]:
                        label = (
                            f'Internal Heat Exchanger {cycle}_{target_cycle}'
                            )
                        self.components[label] = HeatExchanger(label)
                else:
                    label = (
                        'Internal Heat Exchanger '
                        + f'{cycle}_{self.int_heatex[cycle]}'
                        )
                    self.components[label] = HeatExchanger(label)

    def generate_topology(self):
        """Generate the heat pump topology based on defined components."""
        self.set_conn(
            'valve1_to_evaporator1',
            'Valve 1', 'out1',
            'Evaporator 1', 'in2'
            )

        self.set_conn(
            f'heatsource_ff_to_heatsource_pump',
            'Heat Source Feed Flow', 'out1',
            'Heat Source Recirculation Pump', 'in1'
            )
        self.set_conn(
            'heatsource_pump_to_evaporator1',
            'Heat Source Recirculation Pump', 'out1',
            'Evaporator 1', 'in1'
            )
        self.set_conn(
            'evaporator1_to_heatsource_bf',
            'Evaporator 1', 'out1',
            'Heat Source Back Flow', 'in1'
            )

        self.set_conn(
            f'heatsink_cc_to_heatsink_pump',
            'Consumer Cycle Closer', 'out1',
            'Consumer Recirculation Pump', 'in1'
            )
        self.set_conn(
            f'heatsink_pump_to_cond{self.nr_cycles}',
            'Consumer Recirculation Pump', 'out1',
            f'Condenser {self.nr_cycles}', 'in2'
            )
        self.set_conn(
            f'cond{self.nr_cycles}_to_consumer',
            f'Condenser {self.nr_cycles}', 'out2',
            'Consumer', 'in1'
            )
        self.set_conn(
            'consumer_to_heatsink_cc',
            'Consumer', 'out1',
            'Consumer Cycle Closer', 'in1'
            )

        for cycle in range(1, self.nr_cycles+1):
            self.set_conn(
                f'cc{cycle}_to_valve{cycle}',
                f'Cycle Closer {cycle}', 'out1',
                f'Valve {cycle}', 'in1'
                )

            if cycle != 1:
                self.set_conn(
                   f'valve{cycle}_to_heat_ex{cycle-1}_{cycle}',
                   f'Valve {cycle}', 'out1',
                   f'Heat Exchanger {cycle-1}_{cycle}', 'in2'
                   )

            cycle_int_heatex = list()
            for i in range(1, self.nr_cycles+1):
                if i in self.int_heatex:
                    if type(self.int_heatex[i]) == int:
                        if self.int_heatex[i] == cycle:
                            cycle_int_heatex.append(i)
                    elif type(self.int_heatex[i]) == list:
                        if cycle in self.int_heatex[i]:
                            cycle_int_heatex.append(i)

            last_int_heatex = ''
            for c_int_heatex in cycle_int_heatex:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            (f'evaporator{cycle}_to_'
                             + f'int_heatex{c_int_heatex}_{cycle}'),
                            f'Evaporator 1', 'out2',
                            f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                            'in2'
                            )
                    else:
                        self.set_conn(
                            (f'heatex{cycle-1}_{cycle}_to_'
                             + f'int_heatex{c_int_heatex}_{cycle}'),
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                            'in2'
                            )
                else:
                    self.set_conn(
                        (f'int_heatex{last_int_heatex}_{cycle}'
                         + f'_to_int_heatex{c_int_heatex}_{cycle}'),
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Internal Heat Exchanger {c_int_heatex}_{cycle}',
                        'in2'
                        )
                last_int_heatex = c_int_heatex

            if cycle in self.intercooler:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            f'evaporator1_to_comp{cycle}-1',
                            f'Evaporator 1', 'out2',
                            f'Compressor {cycle}-1', 'in1'
                            )
                    else:
                        self.set_conn(
                            f'heatex{cycle-1}_{cycle}_to_comp{cycle}',
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Compressor {cycle}-1', 'in1'
                            )
                else:
                    self.set_conn(
                        f'int_heatex{last_int_heatex}_{cycle}_to_comp{cycle}',
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Compressor {cycle}-1', 'in1'
                        )
                for i in range(1, self.intercooler[cycle]['amount']+1):
                    self.set_conn(
                        f'comp{cycle}-{i}_to_intercooler{cycle}-{i}',
                        f'Compressor {cycle}-{i}', 'out1',
                        f'Intercooler {cycle}-{i}', 'in1'
                        )
                    self.set_conn(
                        f'intercooler{cycle}-{i}_to_comp{cycle}-{i+1}',
                        f'Intercooler {cycle}-{i}', 'out1',
                        f'Compressor {cycle}-{i+1}', 'in1'
                        )
                if cycle == self.nr_cycles:
                    self.set_conn(
                        (f'comp{cycle}-{self.intercooler[cycle]["amount"]+1}'
                         + f'_to_cond{cycle}'),
                        (f'Compressor {cycle}'
                         + f'-{self.intercooler[cycle]["amount"]+1}'),
                        'out1',
                        f'Condenser {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        (f'comp{cycle}-{self.intercooler[cycle]["amount"]+1}'
                         + f'_to_heatex{cycle}_{cycle+1}'),
                        (f'Compressor {cycle}'
                         + f'-{self.intercooler[cycle]["amount"]+1}'),
                        'out1',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'in1'
                        )

            else:
                if not last_int_heatex:
                    if cycle == 1:
                        self.set_conn(
                            f'evaporator1_to_comp{cycle}',
                            f'Evaporator 1', 'out2',
                            f'Compressor {cycle}', 'in1'
                            )
                    else:
                        self.set_conn(
                            f'heatex{cycle-1}_{cycle}_to_comp{cycle}',
                            f'Heat Exchanger {cycle-1}_{cycle}', 'out2',
                            f'Compressor {cycle}', 'in1'
                            )
                else:
                    self.set_conn(
                        f'int_heatex{last_int_heatex}_{cycle}_to_comp{cycle}',
                        f'Internal Heat Exchanger {last_int_heatex}_{cycle}',
                        'out2',
                        f'Compressor {cycle}', 'in1'
                        )
                if cycle == self.nr_cycles:
                    self.set_conn(
                        f'comp{cycle}_to_cond{cycle}',
                        f'Compressor {cycle}', 'out1',
                        f'Condenser {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        f'comp{cycle}_to_heatex{cycle}_{cycle+1}',
                        f'Compressor {cycle}', 'out1',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'in1'
                        )

            int_heatexs = [
                comp for comp in self.components
                if f'Internal Heat Exchanger {cycle}' in comp
                ]
            int_heatexs.sort(reverse=True)
            last_int_heatex = ''
            for int_heatex in int_heatexs:
                int_heatex_idx = int_heatex.split(' ')[-1]
                if not last_int_heatex:
                    if cycle == self.nr_cycles:
                        self.set_conn(
                            f'cond{cycle}_to_int_heatex{int_heatex_idx}',
                            f'Condenser {cycle}', 'out1',
                            int_heatex, 'in1'
                            )
                    else:
                        self.set_conn(
                            (f'heatex{cycle}_{cycle+1}'
                             + f'_to_int_heatex{int_heatex_idx}'),
                            f'Heat Exchanger {cycle}_{cycle+1}', 'out1',
                            int_heatex, 'in1'
                            )
                else:
                    last_int_heatex_idx = last_int_heatex.split(' ')[-1]
                    self.set_conn(
                        (f'int_heatex{last_int_heatex_idx}'
                         + f'_to_int_heatex{int_heatex_idx}'),
                        last_int_heatex, 'out1',
                        int_heatex, 'in1'
                        )
                last_int_heatex = int_heatex

            if not last_int_heatex:
                if cycle == self.nr_cycles:
                    self.set_conn(
                        f'cond{cycle}_to_cc{cycle}',
                        f'Condenser {cycle}', 'out1',
                        f'Cycle Closer {cycle}', 'in1'
                        )
                else:
                    self.set_conn(
                        f'heatex{cycle}_{cycle+1}_to_cc{cycle}',
                        f'Heat Exchanger {cycle}_{cycle+1}', 'out1',
                        f'Cycle Closer {cycle}', 'in1'
                        )
            else:
                last_int_heatex_idx = last_int_heatex.split(' ')[-1]
                self.set_conn(
                    f'int_heatex{last_int_heatex_idx}_to_cc{cycle}',
                    last_int_heatex, 'out1',
                    f'Cycle Closer {cycle}', 'in1'
                    )

    def set_conn(self, label, comp_out, outlet, comp_in, inlet):
        """
        Set connections between components.

        Parameters
        ----------
        label : str
            name of connection (also used as label attribute within the
            generated TESPy object)

        comp_out : tespy.components.component.Component
            component from which the connection originates

        outlet : str
            name of outlet of comp_out (e.g. 'out1')

        comp_in : tespy.components.component.Component
            component where the connection terminates

        inlet : str
            name of inlet of comp_in (e.g. 'in1')
        """
        self.connections[label] = Connection(
            self.components[comp_out], outlet,
            self.components[comp_in], inlet,
            label=label
            )
        self.nw.add_conns(self.connections[label])

    def delete_component(self, component):
        """
        Delete component and all associated connections from Heatpump.

        Parameters
        ----------
        component : str
            label of component to be deleted
        """
        if component not in self.components.keys():
            print(f'No component with label {component} found.')
            return

        del self.components[component]
        print(f'Component {component} succesfully deleted from Heatpump.')

        connections_copy = self.connections.copy()

        for label, connection in self.connections.items():
            is_source = component == connection.source.label
            is_target = component == connection.target.label
            if is_source or is_target:
                self.nw.del_conns(connection)
                del connections_copy[label]
                print(f'Connection {label} succesfully deleted from Heatpump.')

        self.connections = connections_copy


class HeatpumpSingleStage(Heatpump):
    """
    Generic and stable single stage heat pump (opt. internal heat exchanger).

    Parameters
    ----------
    param : dict
        Dictionairy containing key parameters of the heat pump cycle
    """

    def __init__(self, param):
        fluids = ['water', param['refrigerant']]

        if not param['int_heatex']:
            Heatpump.__init__(self, fluids, nr_cycles=1)
        else:
            Heatpump.__init__(self, fluids, nr_cycles=1, int_heatex={1: 1})

        self.param = param
        self.parametrize_components()
        self.busses = dict()
        self.initialized = False

    def parametrize_components(self):
        """Parametrize components of single stage heat pump."""
        self.components['Consumer Recirculation Pump'].set_attr(
            eta_s=0.8, design=['eta_s'], offdesign=['eta_s_char']
            )

        self.components['Heat Source Recirculation Pump'].set_attr(
            eta_s=0.8, design=['eta_s'], offdesign=['eta_s_char']
            )

        self.components['Compressor 1'].set_attr(
            eta_s=0.85, design=['eta_s'], offdesign=['eta_s_char']
            )

        self.components['Condenser 1'].set_attr(
            pr1=0.99, pr2=0.99, design=['pr2'],
            offdesign=['zeta2', 'kA_char']
                    )

        kA_char1 = ldc('heat exchanger', 'kA_char1', 'DEFAULT', CharLine)
        kA_char2 = ldc(
            'heat exchanger', 'kA_char2', 'EVAPORATING FLUID', CharLine
            )

        self.components['Evaporator 1'].set_attr(
            pr1=0.98, pr2=0.98, kA_char1=kA_char1, kA_char2=kA_char2,
            design=['pr1'], offdesign=['zeta1', 'kA_char']
            )

        self.components['Consumer'].set_attr(
            pr=0.99, design=['pr'], offdesign=['zeta']
            )

        if self.param['int_heatex']:
            self.components['Internal Heat Exchanger 1_1'].set_attr(
                pr1=0.99, pr2=0.99,
                offdesign=['zeta1', 'zeta2']
                )

    def init_simulation(self):
        """Perform initial connection parametrization with starting values."""
        h_bottom_right = CP.PropsSI(
            'H', 'Q', 1, 'T', self.param['T_heatsource_bf'] - 5 + 273,
            self.param['refrigerant']
            ) * 1e-3
        p_evap = CP.PropsSI(
            'P', 'Q', 1, 'T', self.param['T_heatsource_bf'] - 5 + 273,
            self.param['refrigerant']
            ) * 1e-5

        h_top_left = CP.PropsSI(
            'H', 'Q', 0, 'T', self.param['T_consumer_ff'] + 5 + 273,
            self.param['refrigerant']
            ) * 1e-3
        p_cond = CP.PropsSI(
            'P', 'Q', 0, 'T', self.param['T_consumer_ff'] + 5 + 273,
            self.param['refrigerant']
            ) * 1e-5

        if not self.param['int_heatex']:
            self.connections['evaporator1_to_comp1'].set_attr(x=1, p=p_evap)
            self.connections['cond1_to_cc1'].set_attr(
                p=p_cond, fluid={'water': 0, self.param['refrigerant']: 1}
                )
        else:
            self.connections['evaporator1_to_int_heatex1_1'].set_attr(
                x=1, p=p_evap
                )
            self.connections['cond1_to_int_heatex1_1'].set_attr(
                p=p_cond, fluid={'water': 0, self.param['refrigerant']: 1}
                )
            self.connections['int_heatex1_1_to_cc1'].set_attr(
                h=(h_top_left - (h_bottom_right - h_top_left) * 0.05)
                )

        self.connections['cond1_to_consumer'].set_attr(
            T=self.param['T_consumer_ff'], p=self.param['p_consumer_ff'],
            fluid={'water': 1, self.param['refrigerant']: 0}
            )

        self.connections['consumer_to_heatsink_cc'].set_attr(
            T=self.param['T_consumer_bf']
            )

        self.connections['heatsource_ff_to_heatsource_pump'].set_attr(
            T=self.param['T_heatsource_ff'], p=self.param['p_heatsource_ff'],
            fluid={'water': 1, self.param['refrigerant']: 0},
            offdesign=['v']
            )

        self.connections['evaporator1_to_heatsource_bf'].set_attr(
            T=self.param['T_heatsource_bf'], p=self.param['p_heatsource_ff'],
            design=['T']
            )

        mot_x = np.array([
            0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55,
            0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1, 1.05, 1.1, 1.15,
            1.2, 10
            ])
        mot_y = 1 / (np.array([
            0.01, 0.3148, 0.5346, 0.6843, 0.7835, 0.8477, 0.8885, 0.9145,
            0.9318, 0.9443, 0.9546, 0.9638, 0.9724, 0.9806, 0.9878, 0.9938,
            0.9982, 1.0009, 1.002, 1.0015, 1, 0.9977, 0.9947, 0.9909, 0.9853,
            0.9644
            ]) * 0.98)

        mot = CharLine(x=mot_x, y=mot_y)

        self.busses['power'] = Bus('total compressor power')
        self.busses['power'].add_comps(
            {'comp': self.components['Compressor 1'], 'char': mot},
            {'comp': self.components['Consumer Recirculation Pump'],
             'char': mot},
            {'comp': self.components['Heat Source Recirculation Pump'],
             'char': mot}
            )

        self.busses['heat'] = Bus('total delivered heat')
        self.busses['heat'].add_comps({'comp': self.components['Consumer']})

        self.nw.add_busses(self.busses['power'], self.busses['heat'])

        self.busses['heat'].set_attr(P=self.param['Q_N'])

        self.solve_design()
        self.initialized = True

    def design_simulation(self):
        """Perform final connection parametrization with desired values."""
        if not self.initialized:
            print(
                'Heat pump has not been initialized via the "init_simulation" '
                + 'method. Therefore the design simulation probably will not '
                + 'converge.'
                )
            return

        if not self.param['int_heatex']:
            self.connections['evaporator1_to_comp1'].set_attr(p=None)
            self.components['Evaporator 1'].set_attr(
                ttd_l=5, design=['pr1', 'ttd_l']
                )

            self.connections['cond1_to_cc1'].set_attr(p=None)
            self.components['Condenser 1'].set_attr(
                ttd_u=5, design=['pr2', 'ttd_u']
                )

            self.connections['comp1_to_cond1'].set_attr(h=None)
            self.components['Compressor 1'].set_attr(
                eta_s=0.85, design=['eta_s'], offdesign=['eta_s_char']
                )
        else:
            self.connections['evaporator1_to_int_heatex1_1'].set_attr(p=None)
            self.components['Evaporator 1'].set_attr(
                ttd_l=5, design=['pr1', 'ttd_l']
                )

            self.connections['cond1_to_int_heatex1_1'].set_attr(p=None)
            self.components['Condenser 1'].set_attr(
                ttd_u=5, design=['pr2', 'ttd_u']
                )

            self.connections['int_heatex1_1_to_cc1'].set_attr(h=None)
            self.connections['int_heatex1_1_to_comp1'].set_attr(
                T=Ref(
                    self.connections['evaporator1_to_int_heatex1_1'],
                    1, self.param['deltaT_int_heatex']
                    )
                )

        self.solve_design()

    def solve_design(self):
        """Perform simulation with 'design' mode."""
        self.nw.solve('design')
        self.nw.print_results()
        self.cop = abs(self.busses['heat'].P.val)/self.busses['power'].P.val
        print(f'COP = {self.cop:.4}')

    def generate_logph(self, open_file=True):
        """Plot the heat pump cycle in logp-h-diagram of chosen refrigerant."""
        if not self.param['int_heatex']:
            results = {
                self.components['Valve 1'].label:
                    self.components['Valve 1'].get_plotting_data()[1],
                self.components['Evaporator 1'].label:
                    self.components['Evaporator 1'].get_plotting_data()[2],
                self.components['Compressor 1'].label:
                    self.components['Compressor 1'].get_plotting_data()[1],
                self.components['Condenser 1'].label:
                    self.components['Condenser 1'].get_plotting_data()[1]
                }
        else:
            label_int_heatex = 'Internal Heat Exchanger 1_1'

            results = {
                self.components['Internal Heat Exchanger 1_1'].label + ' hot':
                    self.components[label_int_heatex].get_plotting_data()[1],
                self.components['Valve 1'].label:
                    self.components['Valve 1'].get_plotting_data()[1],
                self.components['Evaporator 1'].label:
                    self.components['Evaporator 1'].get_plotting_data()[2],
                self.components['Internal Heat Exchanger 1_1'].label + ' cold':
                    self.components[label_int_heatex].get_plotting_data()[2],
                self.components['Compressor 1'].label:
                    self.components['Compressor 1'].get_plotting_data()[1],
                self.components['Condenser 1'].label:
                    self.components['Condenser 1'].get_plotting_data()[1]
                }

        diagram = FluidPropertyDiagram(fluid=self.param['refrigerant'])
        diagram.set_unit_system(T='°C', h='kJ/kg', p='bar')

        for key, data in results.items():
            results[key]['datapoints'] = diagram.calc_individual_isoline(
                **data
                )

        isoT = np.arange(-100, 350, 25)

        ymin = 1e0
        ymax = 3e2

        if self.param['refrigerant'] == 'NH3':
            isoS = np.arange(0, 10000, 500)

            xmin = 250
            xmax = 2250

            infocoords = (0.9, 0.87)

        elif self.param['refrigerant'] == 'R1234ZE':
            isoS = np.arange(0, 2200, 50)

            xmin = 150
            xmax = 500

            infocoords = (0.9, 0.87)

        elif self.param['refrigerant'] == 'R134A':
            isoS = np.arange(0, 3000, 100)

            xmin = 100
            xmax = 600

            infocoords = (0.895, 0.8775)

        elif self.param['refrigerant'] == 'R245FA':
            isoS = np.arange(0, 4000, 100)

            xmin = 100
            xmax = 600
            ymin = 1e-1

            infocoords = (0.865, 0.86)

        # draw isolines
        diagram.set_isolines(T=isoT, s=isoS)
        diagram.calc_isolines()
        diagram.set_limits(x_min=xmin, x_max=xmax, y_min=ymin, y_max=ymax)
        diagram.draw_isolines(diagram_type='logph')

        for i, key in enumerate(results.keys()):
            datapoints = results[key]['datapoints']
            if key == 'Compressor 1':
                diagram.ax.plot(
                    datapoints['h'][1:], datapoints['p'][1:], color='#EC6707'
                    )
                diagram.ax.scatter(
                    datapoints['h'][1], datapoints['p'][1], color='#B54036',
                    label=f'$\\bf{i+1:.0f}$: {key}', s=100, alpha=0.5
                    )
                diagram.ax.annotate(
                    f'{i+1:.0f}', (datapoints['h'][1], datapoints['p'][1]),
                    ha='center', va='center', color='w'
                    )
            else:
                diagram.ax.plot(
                    datapoints['h'], datapoints['p'], color='#EC6707'
                    )
                diagram.ax.scatter(
                    datapoints['h'][0], datapoints['p'][0], color='#B54036',
                    label=f'$\\bf{i+1:.0f}$: {key}', s=100, alpha=0.5
                    )
                diagram.ax.annotate(
                    f'{i+1:.0f}', (datapoints['h'][0], datapoints['p'][0]),
                    ha='center', va='center', color='w'
                    )

        # display info box containing key parameters
        info = (
            '$\\bf{{Wärmepumpe}}$\n'
            + f'Setup {self.param["setup"]}\n'
            + 'Betriebsdaten:\n'
            + f'\t $\\dot{{Q}}_N = ${abs(self.param["Q_N"])*1e-6:.3} $MW$\n'
            + f'\t $COP = ${self.cop:.2f}\n'
            + 'Kältemittel:\n'
            + f'\t ${self.param["refrigerant"]}$\n'
            + 'Wärmequelle:\n'
            + f'\t $T_{{VL}} = ${self.param["T_heatsource_ff"]} °C\n'
            + f'\t $T_{{RL}} = ${self.param["T_heatsource_bf"]} °C\n'
            )

        if self.param['int_heatex']:
            info += (
                'Unterkühlung/Überhitzung:\n'
                + f'\t $\\Delta T_{{IHX}} = ${self.param["deltaT_int_heatex"]}'
                + ' °C\n'
                )

        info += (
            'Wärmesenke:\n'
            + f'\t $T_{{VL}} = ${self.param["T_consumer_ff"]} °C\n'
            + f'\t $T_{{RL}} = ${self.param["T_consumer_bf"]} °C'
            )

        diagram.ax.annotate(
            info, infocoords, xycoords='axes fraction',
            ha='left', va='center', color='k',
            bbox=dict(boxstyle='round,pad=0.3', fc='white')
            )

        diagram.ax.legend(loc='upper left')
        diagram.ax.set_xlim(xmin, xmax)
        diagram.ax.set_ylim(ymin, ymax)

        if not self.param['int_heatex']:
            filename = (
                f'Diagramme\\Setup_{self.param["setup"]}\\'
                + f'logph_{self.param["refrigerant"]}'
                + f'_{self.param["T_heatsource_bf"]}'
                + f'_{self.param["T_consumer_ff"]}.pdf'
                )
        else:
            filename = (
                f'Diagramme\\Setup_{self.param["setup"]}\\'
                + f'logph_{self.param["refrigerant"]}'
                + f'_{self.param["T_heatsource_bf"]}'
                + f'_{self.param["T_consumer_ff"]}'
                + f'_dT{self.param["deltaT_int_heatex"]}K.pdf'
                )

        diagram.save(filename)
        if open_file:
            os.startfile(filename)


# %% Executable
if __name__ == '__main__':
    # hp = Heatpump(
    #     ['water', 'NH3'], nr_cycles=2, int_heatex={2: [1, 2]},
    #     intercooler={1: {'amount': 2, 'type': 'HeatExchanger'}}
    #     )

    import json
    with open('parameter.json', 'r') as file:
        param = json.load(file)

    hp = HeatpumpSingleStage(param)
    hp.init_simulation()
    hp.design_simulation()
    hp.generate_logph()
