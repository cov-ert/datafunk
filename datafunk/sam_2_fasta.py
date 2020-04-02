from Bio import SeqIO
import pysam
import re, itertools
import sys, warnings

"""
# SAM CIGAR operations

Op BAM  Description                                             Consumes_query  Consumes_reference  Ben
---------------------------------------------------------------------------------------------------------------------------------------
 M  0   alignment match (can be a sequence match or mismatch)   yes             yes                 include seq, advance both
 I  1   insertion relative to the reference                     yes             no                  don't include seq, advance q
 D  2   deletion relative to the reference                      no              yes                 include seq as gap, advance r
 N  3   skipped region from the reference                       no              yes                 include seq as gap?, advance r?
 S  4   soft clipping (clipped sequences present in SEQ)        yes             no                  don't include seq, advance q?
 H  5   hard clipping (clipped sequences NOT present in SEQ)    no              no                  don't include seq, advance neither?
 P  6   padding (silent deletion from padded reference)         no              no                  don't include seq, advance neither?
 =  7   sequence match                                          yes             yes                 include seq, advance both
 X  8   sequence mismatch                                       yes             yes                 include seq, advance both
---------------------------------------------------------------------------------------------------------------------------------------
"""

# consumes_query     = {'M': True, 'I': True, 'D': False, 'N': False, 'S': True, 'H': False, 'P': False, '=': True, 'X': True}
# consumes_reference = {'M': True, 'I': False, 'D': True, 'N': True, 'S': False, 'H': False, 'P': False, '=': True, 'X': True}

# A dict of functions to apply to CIGAR operations
lambda_dict = {'M': (lambda query_start, ref_start, length, seq: (query_start + length, ref_start + length, seq[query_start:query_start + length] )),
               'I': (lambda query_start, ref_start, length, seq: (query_start + length, ref_start         , ''                                    )),
               'D': (lambda query_start, ref_start, length, seq: (query_start         , ref_start + length, '-' * length                          )),
               'N': (lambda query_start, ref_start, length, seq: (query_start         , ref_start + length, '-' * length                          )),
               'S': (lambda query_start, ref_start, length, seq: (query_start + length, ref_start         , ''                                    )),
               'H': (lambda query_start, ref_start, length, seq: (query_start         , ref_start         , ''                                    )),
               'P': (lambda query_start, ref_start, length, seq: (query_start         , ref_start         , ''                                    )),
               '=': (lambda query_start, ref_start, length, seq: (query_start + length, ref_start + length, seq[query_start:query_start + length] )),
               'X': (lambda query_start, ref_start, length, seq: (query_start + length, ref_start + length, seq[query_start:query_start + length] ))}

def parse_sam_line(AlignedSegment):
    """
    d is a dictionary with SAM field names as keys and their value from
    one line of a SAM alignment as values
    """
    line = str(AlignedSegment)
    names = ['QNAME', 'FLAG', 'RNAME', 'POS', 'MAPQ', 'CIGAR', 'RNEXT', 'PNEXT', 'TLEN', 'SEQ', 'QUAL']
    d = {x: y for x,y in zip(names, line.split()[0:11])}
    return(d)


def split_sam_cigar_operation(one_operation):
    """
    o is a tuple with the format(operation, size)
    e.g. ('M', 2377) or ('D', 1)
    """
    type = one_operation[-1:]
    size = int(one_operation[:-1])
    o = (type, size)
    return(o)


def split_sam_cigar(cigar):
    """
    m is a list of strings (e.g. ['1000M', '4I'])
    """
    r = re.compile('\d{1,}[A-Z]{1}')
    l = re.findall(r, cigar)
    return(l)


def get_sam_cigar_operations(cigar):
    """
    operations is a list of tuples that correspond to
    operations to apply in order:
    [('M', 10000),('I', 3),('M', 19763)]
    """
    operations_raw = split_sam_cigar(cigar)
    operations = [split_sam_cigar_operation(x) for x in operations_raw]
    return(operations)


def get_one_string(sam_line, rlen):
    """
    Transform one line of the SAM alignment into sample sequence in unpadded
    reference coordinates (insertions relative to the reference are omitted).
    """
    # parsed sam line
    aln_info_dict = parse_sam_line(sam_line)

    # CIGAR STRING
    CIGAR = aln_info_dict['CIGAR']

    # According to the SAM spec:
    # "POS: 1-based leftmost mapping POSition of the first CIGAR operation that
    # “consumes” a reference base (see table above)."
    # But note that pysam converts this field to 0-bsaed coordinates for us
    POS = int(aln_info_dict['POS'])

    # Query seq:
    SEQ = aln_info_dict['SEQ']

    # According to the SAM spec:
    # "If POS < 1, unmapped read, no assumptions can be made about RNAME and CIGAR"
    # But note that pysam converts POS to 0-bsaed coordinates for us (as above)
    if POS < 0:
        # TO DO: SOME SENSIBLE RETURN HERE
        return(None)

    # parse the CIGAR string to get the operations:
    operations = get_sam_cigar_operations(CIGAR)

    # left-pad the new sequence with gaps if required
    new_seq = '*' * POS

    # then build the sequence:
    qstart = 0
    rstart = POS
    for o in operations:
        operation = o[0]
        size = o[1]

        # based on this CIGAR operation, call the relavent lambda function
        # from the dict of lambda functions, returns sequence to be appended
        # and the next set of coordinates
        new_qstart, new_rstart, extension = lambda_dict[operation](qstart, rstart, size, SEQ)

        new_seq = new_seq + extension

        qstart = new_qstart
        rstart = new_rstart

    rightpad = '*' * (rlen - len(new_seq))

    new_seq = new_seq + rightpad

    return(new_seq)


def check_and_get_flattened_site(site):
    """
    A per-site check that there isn't any ambiguity between
    alignments within a single sequence
    """

    check = sum([x.isalpha() for x in site])
    if check > 1:
        warnings.warn('ambiguous overlapping alignment - grep alignment for "&"s')
        return('&')

    # because {A, C, G, T} > {-} > {*}, we can use max()
    base = max(site)
    return(base)


def swap_in_gaps_Ns(seq):
    """
    replace internal runs of '*'s with 'N's
    and external runs of '*'s with '-'s
    """
    r_internal = re.compile('[A-Z]\*+[A-Z]')
    for x in re.findall(r_internal, seq):
        seq = seq.replace(x, x[0] + x[1:-1].replace('*','N') + x[-1])

    r_left = re.compile('^\*+[A-Z]')
    m_left = re.search(r_left, seq)
    if m_left:
        g_left = m_left.group()
        seq = seq.replace(g_left, g_left[:-1].replace('*','-') + g_left[-1])

    r_right = re.compile('[A-Z]\*+$')
    m_right = re.search(r_right, seq)
    if m_right:
        g_right = m_right.group()
        seq = seq.replace(g_right,  g_right[0] + g_right[1:].replace('*','-'))

    return(seq)


def get_seq_from_block(sam_block, rlen):

    block_lines_sites_list = [get_one_string(sam_line, rlen) for sam_line in sam_block]

    if len(block_lines_sites_list) == 1:
        seq_flat_no_internal_gaps = swap_in_gaps_Ns(block_lines_sites_list[0])
        return(seq_flat_no_internal_gaps)

    else:
        # # as an alternative to check_and_get_flattened_site() we can flatten
        # # the site with no checks (about three times as fast):
        # flattened_site_list = [max(x) for x in zip(*block_lines_sites_list)]

        flattened_site_list = [check_and_get_flattened_site(x) for x in zip(*[list(x) for x in block_lines_sites_list])]
        seq_flat = ''.join(flattened_site_list)

        # replace central '*'s with 'N's, and external '*'s with '-'s
        seq_flat_no_internal_gaps = swap_in_gaps_Ns(seq_flat)
        return(seq_flat_no_internal_gaps)