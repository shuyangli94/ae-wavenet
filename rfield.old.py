# An instance of Rfield represents a windowed, convolution-like transformation
# of an input tensor to an output tensor.  The relationship is defined both in
# a tensor index coordinates, and physical coordinates.  Multiple Rfield's may
# be chained together in the output of one is fed to the input of the other.
# The relationship in index coordinates maps an input index range to an output
# index range.

import fractions 
import numpy as np
import math

class _Stats(object):
    '''Describes a 1D tensor of positioned elements''' 
    def __init__(self, l_pad, r_pad, spc, vspc, l_pos, r_pos, src=None,
            dst=None):
        self.l_pad = l_pad
        self.r_pad = r_pad
        self.spc = spc
        self.vspc = vspc

        # Assuming the previous tensor's left element is at zero in physical
        # coordinates, this tensor starts at l_pos
        self.l_pos = l_pos

        # Assuming the previous tensor's right element is at zero in physical
        # coordinates, this tensor starts at -r_pos
        self.r_pos = r_pos
        self.src = src
        self.dst = dst
        self.nv = None 

    def __repr__(self):
        src_name = 'None' if self.src is None else self.src.name
        dst_name = 'None' if self.dst is None else self.dst.name

        return 'l_pad: {}, r_pad: {}, nv: {}, spc: {}, vspc: {}, l_pos: {}, ' \
                'r_pos: {}, span(): {}, src: {}, dst: {}\n'.format(
                        self.l_pad, self.r_pad, self.nv, self.spc, self.vspc,
                        self.l_pos, self.r_pos, self.span(), src_name, dst_name)

    def symbolic(self):
        in_pad = (self.vspc // self.spc) - 1
        spc_str = ' {}P '.format(in_pad)
        body = spc_str.join(['V'] * self.nv) 
        l_pad = '{}L'.format(self.l_pad)
        r_pad = '{}R'.format(self.r_pad)
        return ' '.join([l_pad, body, r_pad])

    def span(self):
        if self.nv is None:
            return None
        return (self.nv - 1) * self.vspc + self.l_pos - self.r_pos + 1

    def gen(self):
        '''Produce an iterator forward through the chain of stats'''
        s = self
        while s is not None:
            yield s
            s = None if s.dst is None else s.dst.dst

    def rgen(self):
        '''Produce an iterator backward through the chain of stats'''
        s = self
        while s is not None:
            yield s
            s = None if s.src is None else s.src.src

    def li_pos(self, index):
        """The"""



def print_stats(beg, xpad='x', ipad='o', data='*'):
    '''pretty print a symbolic stack of 1D window-based tensor calculations
    represented by 'stats', showing strides, padding, and dilation.  Generate
    stats using Rfield::gen_stats()'''

    def _dilate_string(string, space_sym, spacing):
        if len(string) == 0:
            return ''
        space_str = space_sym * (spacing - 1)
        return string[0] + ''.join(space_str + s for s in string[1:])

    def l_pad_pos(st):
        return st.l_pos - st.l_pad * st.spc

    def r_pad_pos(st):
        return st.r_pos + st.r_pad * st.spc

    stats = list(beg.src.gen())
    min_pad_pos = min(l_pad_pos(st) for st in stats)
    max_pad_pos = max(r_pad_pos(st) for st in stats)

    print('\n')
    # We print output at the top, with the earlier steps going down.
    for st in reversed(stats):
        l_spc = ' ' * (l_pad_pos(st) - min_pad_pos)
        r_spc = ' ' * (max_pad_pos - r_pad_pos(st))
        core = _dilate_string(data * st.nv, ipad, round(st.vspc / st.spc))
        body = xpad * st.l_pad + core + xpad * st.r_pad
        body_dil = _dilate_string(body, ' ', round(st.spc))
        s = '|' + l_spc + body_dil + r_spc + '|'
        print(s)


class Rfield(object):
    '''
    An instance of Rfield describes one 1D scanning-window transformation
    such as a convolution, transpose convolution or fourier transform.  Chain
    instances together with the 'parent' field, to represent a feed-forward
    chain of transformations.

    Then, use the final child to calculate needed input size for a desired
    output size, and offsets relative to the input.
    '''
    def __init__(self, filter_info, padding=(0, 0), stride=1,
            is_downsample=True, parent=None, name=None):
        self.parent = parent
        self.child = None
        self.l_pad = padding[0]
        self.r_pad = padding[1]
        self.name = name
        self.src = None
        self.dst = None

        if self.parent is not None:
            self.parent.child = self

        # stride_ratio is ratio of output spacing to input spacing
        if is_downsample:
            self.stride_ratio = fractions.Fraction(stride, 1)
        else:
            self.stride_ratio = fractions.Fraction(1, stride)

        if isinstance(filter_info, tuple):
            self.l_wing_sz = filter_info[0]
            self.r_wing_sz = filter_info[1]
        elif isinstance(filter_info, int):
            total_wing_sz = filter_info - 1
            self.l_wing_sz = total_wing_sz // 2
            self.r_wing_sz = total_wing_sz - self.l_wing_sz
        else:
            raise RuntimeError('filter_info must be either a 2-tuple of '
                    '(l_wing_sz, r_wing_sz) or an integer of filter_sz')

    def __repr__(self):
        return 'name: {}, wing_sizes: {}, stride_ratio: {}, padding: {}\n'.format(
                self.name, (self.l_wing_sz, self.r_wing_sz),
                self.stride_ratio, (self.l_pad, self.r_pad))
    def next(self):
        if self.dst is None:
            raise RuntimeError('Must run gen_stats() first')
        return self.dst.dst

    def prev(self):
        return self.parent

    def _in_stride(self, output_stride_r):
        return output_stride_r / self.stride_ratio

    def _in_spacing(self, out_spc, out_vspc):
        if self.stride_ratio > 1:
            in_spc = out_vspc / self.stride_ratio
            in_vspc = in_spc
        else:
            in_spc = out_vspc
            in_vspc = in_spc / self.stride_ratio
        return in_spc, in_vspc

    @property
    def l_off(self):
        return self.l_wing_sz - self.l_pad

    @property
    def r_off(self):
        return self.r_pad - self.r_wing_sz

    def _local_bounds(self):
        '''For this transformation, calculates the offset between the first
        value elements of the input and the output, assuming output element
        spacing of 1.  Return values must be adjusted by the actual output
        element spacing.
        '''
        # spacing is the distance between any two consecutive elements in this
        # tensor, including padding elements 
        l_off = self.l_wing_sz - self.l_pad
        r_off = self.r_pad - self.r_wing_sz
        return l_off, r_off

    def chain_length(self, other=None):
        '''Get number of links between self and other, or raise an error.
        set other=None to get full chain length'''
        n, cur = 0, self
        while cur != other and cur != None:
            n += 1
            cur = cur.parent
        if cur != other:
            raise RuntimeError('chain ended and stop node not found')
        return n

    def chain_beg(self):
        rf = self
        while rf.prev() is not None:
            rf = rf.prev()
        return rf

    def chain_end(self):
        rf = self
        while rf.next() is not None:
            rf = rf.next()
        return rf

    def _num_in_elem(self, n_out_elem_req):
        '''calculate the number of input value elements (not counting padding
        or dilation elements) needed to produce at least the desired number of
        output elements.  Note that the number of input elements needed to
        produce at least n_out_elem_req may in fact produce more than that.'''
        # See rfield_notes.txt for formulas
        def _spaced(n_el, stride):
            return (n_el - 1) * stride + 1

        lw, rw = self.l_wing_sz, self.r_wing_sz
        lp, rp = self.l_pad, self.r_pad

        # Or: output requested, I: input size needed
        # downsampling: LW + spaced(Or, S) + RW = LP + spaced(I, 1) + RP
        # upsampling  : LW + spaced(Or, 1) + RW = LP + spaced(I, S) + RP
        const = lw + rw - lp - rp

        if self.stride_ratio.denominator == 1:
            # downsampling
            stride = self.stride_ratio.numerator
            n_in_elem = (n_out_elem_req - 1) * stride + 1 + const
        else:
            # upsampling
            stride = self.stride_ratio.denominator
            n_in_elem = math.ceil((n_out_elem_req + stride - 1 + const) / stride)
        return n_in_elem

    def _num_out_elem(self, n_in_elem):
        '''Calculate number of output elements for the given number of
        input elements.'''
        def _spaced(n_el, stride):
            return (n_el - 1) * stride + 1

        lw, rw = self.l_wing_sz, self.r_wing_sz
        lp, rp = self.l_pad, self.r_pad
        const = lw + rw - lp - rp

        if self.stride_ratio.denominator == 1:
            # downsampling
            stride = self.stride_ratio.numerator
            n_out_elem = (n_in_elem - const + stride - 1) // stride
        else:
            # upsampling
            stride = self.stride_ratio.denominator
            n_out_elem = _spaced(n_in_elem, stride) - const
        return n_out_elem

    def _expand_stats_(self):
        '''After the initial backward sweep calculation of numbers of input
        elements necessary for a requested number of output elements, do a forward
        sweep, calculating the number of output elements that would be produced.
        Updates each stat's nv field'''
        rf = self 
        while rf is not None and rf.dst is not None:
            rf.dst.nv = rf._num_out_elem(rf.src.nv)
            rf = rf.dst.dst

    def _normalize_stats_(self):
        '''Adjusts all spacing to be non-fractional, and aligns left and right
        positions'''
        stats = list(self.src.gen())
        
        lcm_denom = fractions.Fraction(np.lcm.reduce(tuple(s.spc.denominator for s
            in stats)))

        for s in stats:
            s.spc = int(s.spc * lcm_denom)
            s.vspc = int(s.vspc * lcm_denom)
            s.l_pos = int(s.l_pos * lcm_denom)
            s.r_pos = int(s.r_pos * lcm_denom)

        min_l_pos = min(s.l_pos for s in stats)
        max_r_pos = max(s.r_pos for s in stats)

        for s in stats: 
            s.l_pos = s.l_pos - min_l_pos
            s.r_pos = s.r_pos - max_r_pos

    def gen_stats(self, source, out_spc=1, out_vspc=1, l_out_pos=0,
            r_out_pos=0, prev_stat=None):
        '''Populate stats members backwards of this chain of transformations.
        Each Rfield in the chain [source, self] (inclusive) will have is src
        and dst fields initialized with a Stats object.  If any transformation
        leads to a zero-length or negative-length tensor, raise exception.
        Does not initialize the .nv field of stats.  Use init_nv() for that.
        '''
        if prev_stat is None:
            prev_stat = _Stats(0, 0, out_spc, out_vspc, l_out_pos, r_out_pos,
                    src=self, dst=None)
        self.dst = prev_stat 

        l_off, r_off = self._local_bounds()

        # This is a check that the architecture is non-vacuous.  A vacuous
        # Rfield is one that can produce an output element with no input.
        n_in_el = self._num_in_elem(1)
        if n_in_el <= 0:
            raise RuntimeError('gen_stats: invalid model architecture results in a'
                    ' output with {} element(s)'.format(n_in_el))

        in_spc, in_vspc = self._in_spacing(out_spc, out_vspc)
        l_in_pos = l_out_pos - l_off * in_spc
        r_in_pos = r_out_pos - r_off * in_spc

        stat = _Stats(self.l_pad, self.r_pad, in_spc, in_vspc, l_in_pos,
                r_in_pos, src=self.parent, dst=self)
        self.src = stat

        if self == source: 
            self._normalize_stats_()
            return 
        else:
            return self.parent.gen_stats(source, in_spc, in_vspc, l_in_pos,
                    r_in_pos, stat)

    def init_nv(self, out_nv_requested):
        '''Populate the .nv field of stats.  Propagates the requested number
        of output value elements backwards, then updates forwards to get
        the actual number'''
        if self.src is None:
            raise RuntimeError('Must call gen_stats() first')

        n_in_el = self._num_in_elem(out_nv_requested)

        if self.parent is None or self.parent.src is None:
            self.src.nv = n_in_el
            self._expand_stats_()
            return 
        else:
            return self.parent.init_nv(n_in_el)


def get_index_range(beg_rf, end_rf, index):
    l_off, r_off = offsets(beg_rf, end_rf)

def offsets(beg_rf, end_rf):
    '''Get relative left and right offsets between the input/output of
    the net which consists of the range [beg, end], inclusive.  gen_stats()
    must be called before this, but the offsets don't depend on the n_out_el
    argument'''
    beg_st = beg_rf.src
    end_st = end_rf.dst
    l_off = (end_st.l_pos - beg_st.l_pos) / beg_st.spc
    r_off = (end_st.r_pos - beg_st.r_pos) / beg_st.spc
    if not (l_off == int(l_off) and r_off == int(r_off)):
        raise RuntimeError(('non-integer offsets found ({}, {}).  For this model '
                + 'architecture, there is not a one-to-one vector element '
                + 'relationship between input and output.  See rfield for an '
                + 'explanation.').format(l_off, r_off))
    return int(l_off), int(r_off)

def condensed(beg_rf, end_rf, name=None):
    '''Produce a single Rfield with the same geometry between input and output
    elements as the chain source->self. '''
    beg_st = beg_rf.src
    end_st = end_rf.dst
    if beg_st is None or end_st is None:
        raise RuntimeError('Must call gen_stats() first')

    l_pad = beg_st.spc * beg_st.l_pad
    r_pad = beg_st.spc * beg_st.r_pad
    filt = (end_st.l_pos - beg_st.l_pos + l_pad, -end_st.r_pos + beg_st.r_pos + r_pad)
    downsample = beg_st.vspc < end_st.vspc
    if downsample: 
        stride = end_st.vspc / beg_st.vspc
    else:
        stride = beg_st.vspc / end_st.vspc
    if stride != int(stride):
        raise RuntimeError('Cannot condense for non-integer stride ratio {}'.format(stride))
    return Rfield(filt, (l_pad, r_pad), int(stride), downsample, None, name)

